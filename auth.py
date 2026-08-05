"""
Camada de autenticacao do Painel NPS.

Mesmo modelo da lojinha.py: login com senha bcrypt, 2FA por SMS (Infobip),
sessao persistente de 24h via token na URL e reset de senha por SMS.

Diferencas em relacao a lojinha:
  - Perfis: 'admin' (ve todas as franquias) e 'comum' (ve apenas as suas).
  - Vinculo usuario -> franquia fica na tabela nps_usuario_franquias.
  - Telefone nao vem da planilha; o admin cadastra pelo painel.
    Usuario sem telefone nao consegue logar (nao ha como enviar o SMS).
"""

import streamlit as st
from sqlalchemy import text
import pandas as pd
from datetime import datetime, timedelta
import bcrypt
import requests
import re
import random
import string
import uuid
import time
import os
import base64

# --- CONEXAO SQL (NEON) ---
conn = st.connection("postgresql", type="sql", pool_pre_ping=True, pool_recycle=300)

# Usuario sem 2FA validado nesta janela precisa refazer o SMS.
HORAS_SESSAO = 24

# --- PERFIS DE ACESSO ---
#   admin    : ve tudo + administra usuarios
#   operacao : ve tudo, mas a aba Usuarios fica somente leitura
#   comum    : ve apenas as franquias vinculadas ao seu cadastro
TIPOS_ACESSO = ("comum", "operacao", "admin")

# Perfis que enxergam a base inteira, sem recorte por franquia.
TIPOS_IRRESTRITOS = ("admin", "operacao")

ROTULO_TIPO = {
    "admin": "Administrador",
    "operacao": "Operação",
    "comum": "Franquias vinculadas",
}


# ==========================================================================
# SCHEMA / MIGRACOES
# ==========================================================================
@st.cache_resource(show_spinner="Conectando ao banco de dados...")
def iniciar_banco_dados():
    """Cria as tabelas do painel NPS se ainda nao existirem. Idempotente."""
    with conn.session as s:
        try:
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS nps_usuarios (
                    id                  SERIAL PRIMARY KEY,
                    usuario             TEXT UNIQUE NOT NULL,
                    senha               TEXT NOT NULL,
                    nome                TEXT NOT NULL,
                    email               TEXT,
                    perfil              TEXT,
                    tipo                TEXT NOT NULL DEFAULT 'comum',
                    telefone            TEXT,
                    ativo               BOOLEAN DEFAULT TRUE,
                    token_sessao        TEXT,
                    token_expira_em     TIMESTAMP,
                    reset_token         TEXT,
                    reset_token_expira  TIMESTAMP,
                    ultimo_acesso       TIMESTAMP,
                    criado_em           TIMESTAMP DEFAULT NOW()
                );
            """))
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS nps_usuario_franquias (
                    id          SERIAL PRIMARY KEY,
                    usuario_id  INTEGER NOT NULL REFERENCES nps_usuarios(id) ON DELETE CASCADE,
                    franquia    TEXT NOT NULL,
                    UNIQUE (usuario_id, franquia)
                );
            """))
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS nps_logs (
                    id          SERIAL PRIMARY KEY,
                    data        TIMESTAMP DEFAULT NOW(),
                    responsavel TEXT,
                    acao        TEXT,
                    detalhes    TEXT
                );
            """))
            s.execute(text("CREATE INDEX IF NOT EXISTS idx_nps_uf_usuario ON nps_usuario_franquias(usuario_id);"))
            s.commit()
        except Exception as e:
            print(f"Erro ao inicializar o banco: {e}")


# ==========================================================================
# HELPERS
# ==========================================================================
def gerar_hash(senha):
    return bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verificar_senha_hash(senha_digitada, hash_armazenado):
    try:
        if not str(hash_armazenado).startswith("$2b$"):
            return senha_digitada == hash_armazenado
        return bcrypt.checkpw(senha_digitada.encode('utf-8'), hash_armazenado.encode('utf-8'))
    except Exception:
        return False


def gerar_senha_aleatoria(tamanho=8):
    caracteres = string.ascii_uppercase + string.digits
    return ''.join(random.choice(caracteres) for _ in range(tamanho))


def formatar_telefone(tel):
    apenas_numeros = re.sub(r'\D', '', str(tel))
    if 10 <= len(apenas_numeros) <= 11:
        apenas_numeros = "55" + apenas_numeros
    return apenas_numeros


def run_query(query_str, params=None, ttl="5m", spinner="Consultando o banco de dados..."):
    """
    Consulta o banco mostrando uma rodinha de progresso.

    O indicador "Running..." nativo do Streamlit fica escondido por CSS
    (ver NPS_app.py); o st.spinner aqui e o que sinaliza a espera ao usuario.
    """
    try:
        with st.spinner(spinner):
            return conn.query(query_str, params=params, ttl=ttl)
    except Exception:
        st.cache_data.clear()
        try:
            with st.spinner("Reconectando ao banco de dados..."):
                conn.reset()
                return conn.query(query_str, params=params, ttl=ttl)
        except Exception:
            st.error("O banco de dados está se reconectando. Atualize a página.")
            return pd.DataFrame()


def run_transaction(query_str, params=None, spinner="Gravando..."):
    with st.spinner(spinner):
        with conn.session as s:
            s.execute(text(query_str), params if params else {})
            s.commit()


def limpar_cache_banco():
    """Descarta o cache das consultas para a proxima leitura vir do Neon."""
    st.cache_data.clear()


def registrar_log(acao, detalhes):
    try:
        resp = st.session_state.get('usuario_nome', 'Sistema')
        run_transaction(
            "INSERT INTO nps_logs (data, responsavel, acao, detalhes) VALUES (NOW(), :resp, :acao, :det)",
            {"resp": resp, "acao": acao, "det": detalhes}
        )
    except Exception as e:
        print(f"Erro log: {e}")


# ==========================================================================
# ENVIO DE MENSAGENS (INFOBIP)
#
# ATENCAO: a Infobip devolve HTTP 200 mesmo quando a mensagem e REJEITADA.
# O status real vem no corpo, em messages[0].status.groupName. Sem checar
# isso, o app acha que enviou e o usuario nunca recebe nada -- foi
# exatamente o que aconteceu com o SMS.
# ==========================================================================
GRUPOS_FALHA = ("REJECTED", "UNDELIVERABLE", "EXPIRED")


def _avaliar_resposta_infobip(response):
    """Traduz a resposta da Infobip em (ok, mensagem_legivel)."""
    if response.status_code not in (200, 201):
        return False, f"HTTP {response.status_code}: {response.text[:300]}"
    try:
        dados = response.json()
        status = dados.get("messages", [{}])[0].get("status", {})
        grupo = str(status.get("groupName", "")).upper()
        if grupo in GRUPOS_FALHA:
            detalhe = status.get("description") or status.get("name") or "rejeitado pela Infobip"
            return False, f"{grupo}: {detalhe}"
        return True, f"aceito pela Infobip ({grupo or 'PENDING'})"
    except Exception:
        return True, "enviado (corpo da resposta nao verificado)"


def _credenciais_infobip():
    return (
        st.secrets["INFOBIP_BASE_URL"].rstrip('/'),
        st.secrets["INFOBIP_API_KEY"],
        {"Authorization": f"App {st.secrets['INFOBIP_API_KEY']}",
         "Content-Type": "application/json", "Accept": "application/json"},
    )


def _conferir_entrega_sms(message_id, tentativas=3, espera=1.5):
    """
    Confere o status real no relatorio de entrega.

    No SMS a recusa e ASSINCRONA: o POST devolve PENDING_ACCEPTED e so o
    relatorio, segundos depois, revela REJECTED_NOT_ENOUGH_CREDITS. Sem esta
    conferencia o painel anuncia "codigo enviado" para uma mensagem que nunca
    vai sair -- foi o que aconteceu quando o saldo da Infobip zerou.

    Retorna (veredito, motivo): veredito False = recusado, True = entregue/aceito,
    None = ainda sem resposta (o normal e seguir em frente).
    """
    try:
        base_url, _, headers = _credenciais_infobip()
    except Exception:
        return None, ""
    for _ in range(tentativas):
        time.sleep(espera)
        try:
            r = requests.get(f"{base_url}/sms/3/reports", headers=headers,
                             params={"messageId": message_id}, timeout=10)
            if r.status_code != 200:
                return None, ""
            for m in r.json().get("results", []):
                st_ = m.get("status", {})
                grupo = str(st_.get("groupName", "")).upper()
                if grupo in GRUPOS_FALHA:
                    erro = (m.get("error") or {}).get("description")
                    return False, f"{st_.get('name')}: {erro or st_.get('description')}"
                if grupo == "DELIVERED":
                    return True, "entregue no aparelho"
        except Exception:
            return None, ""
    return None, ""


def enviar_sms(telefone, mensagem_texto, conferir_entrega=True):
    try:
        base_url, _, headers = _credenciais_infobip()
        tel_final = formatar_telefone(telefone)
        if len(tel_final) < 12:
            return False, f"Numero invalido: {tel_final}"
        payload = {"messages": [{"from": "InfoSMS",
                                 "destinations": [{"to": tel_final}],
                                 "text": mensagem_texto}]}
        r = requests.post(f"{base_url}/sms/2/text/advanced", json=payload, headers=headers, timeout=20)
        ok, detalhe = _avaliar_resposta_infobip(r)
        if not ok:
            return False, f"SMS {detalhe}"

        if conferir_entrega:
            try:
                mid = r.json().get("messages", [{}])[0].get("messageId")
            except Exception:
                mid = None
            if mid:
                veredito, motivo = _conferir_entrega_sms(mid)
                if veredito is False:
                    return False, f"SMS recusado pela Infobip - {motivo}"
                if veredito is True:
                    return True, "SMS entregue no aparelho"
        return ok, f"SMS {detalhe}"
    except Exception as e:
        return False, f"Erro no envio do SMS: {e}"


# Estruturas possiveis de botao para template da categoria AUTHENTICATION.
# O WhatsApp exige que o codigo va TAMBEM no botao de copiar codigo.
#
# A Infobip expoe esse botao como type "URL" -- confirmado por teste real:
# das 4 variantes disparadas, so a "URL" chegou no aparelho. As outras
# retornaram HTTP 200 / PENDING_ENROUTE e foram descartadas depois, sem
# nenhum aviso. Por isso "URL" e o padrao aqui.
VARIANTES_BOTAO = {
    "URL": lambda c: [{"type": "URL", "parameter": c}],
    "COPY_CODE": lambda c: [{"type": "COPY_CODE", "parameter": c}],
    "QUICK_REPLY": lambda c: [{"type": "QUICK_REPLY", "parameter": c}],
    "nenhum": None,
}


def enviar_whatsapp_template(telefone, parametros, nome_template=None, idioma=None, variante_botao=None):
    """
    Envia um template HSM aprovado do WhatsApp.

    O idioma precisa bater EXATAMENTE com o registrado na Infobip
    ("Portuguese (BR)" -> pt_BR). Fica em secrets para ajustar sem mexer no codigo.

    variante_botao: chave de VARIANTES_BOTAO. Se None, usa TEMPLATE_2FA_BOTAO
    do secrets. Templates de autenticacao normalmente precisam de uma delas.
    """
    try:
        base_url, _, headers = _credenciais_infobip()
        sender = st.secrets["INFOBIP_SENDER"]
        nome_template = nome_template or st.secrets.get("TEMPLATE_2FA", "nps_acesso")
        idioma = idioma or st.secrets.get("TEMPLATE_2FA_IDIOMA", "pt_BR")
        if variante_botao is None:
            variante_botao = st.secrets.get("TEMPLATE_2FA_BOTAO", "URL")

        tel_final = formatar_telefone(telefone)
        if len(tel_final) < 12:
            return False, f"Numero invalido: {tel_final}"

        template_data = {"body": {"placeholders": [str(p) for p in parametros]}}
        construtor = VARIANTES_BOTAO.get(variante_botao)
        if construtor and parametros:
            template_data["buttons"] = construtor(str(parametros[0]))

        payload = {"messages": [{
            "from": sender,
            "to": tel_final,
            "content": {"templateName": nome_template,
                        "templateData": template_data,
                        "language": idioma},
        }]}
        r = requests.post(f"{base_url}/whatsapp/1/message/template",
                          json=payload, headers=headers, timeout=20)
        ok, detalhe = _avaliar_resposta_infobip(r)
        return ok, f"WhatsApp [{nome_template}/{idioma}/botao={variante_botao}] {detalhe}"
    except Exception as e:
        return False, f"Erro no envio do WhatsApp: {e}"


def varrer_variantes_whatsapp(telefone, codigo, nome_template=None, idiomas=None):
    """
    Testa combinacoes de idioma x estrutura de botao ate a Infobip aceitar uma.
    Retorna (lista_de_resultados, combinacao_vencedora_ou_None).
    Cada tentativa aceita dispara uma mensagem real -- para no primeiro sucesso.
    """
    idiomas = idiomas or [st.secrets.get("TEMPLATE_2FA_IDIOMA", "pt_BR"), "pt_PT", "en"]
    vistos, resultados, vencedora = set(), [], None
    for idioma in idiomas:
        if idioma in vistos:
            continue
        vistos.add(idioma)
        for variante in ["URL", "COPY_CODE", "QUICK_REPLY", "nenhum"]:
            ok, detalhe = enviar_whatsapp_template(
                telefone, [codigo], nome_template=nome_template,
                idioma=idioma, variante_botao=variante
            )
            resultados.append({"idioma": idioma, "botao": variante, "ok": ok, "detalhe": detalhe})
            if ok:
                vencedora = {"idioma": idioma, "botao": variante}
                return resultados, vencedora
    return resultados, None


def enviar_codigo_2fa(telefone, codigo):
    """
    Entrega o codigo de verificacao. Tenta o template de WhatsApp primeiro
    (canal principal) e cai para SMS se ele falhar.

    Retorna (ok, canal_usado, detalhe).
    """
    ok, det_wpp = enviar_whatsapp_template(telefone, [codigo])
    if ok:
        return True, "WhatsApp", det_wpp

    if not bool(st.secrets.get("FALLBACK_SMS", True)):
        return False, None, det_wpp

    ok_sms, det_sms = enviar_sms(telefone, f"Painel NPS - seu codigo de acesso: {codigo}")
    if ok_sms:
        # O fallback funcionando esconde a falha do canal principal: sem este
        # registro, ninguém percebe que o WhatsApp parou (foi o que aconteceu
        # quando os créditos da Infobip acabaram).
        registrar_log("Fallback 2FA", f"WhatsApp falhou, código foi por SMS. {det_wpp}")
        return True, "SMS", det_sms
    return False, None, f"{det_wpp} | {det_sms}"


# ==========================================================================
# SESSAO
# ==========================================================================
def iniciar_estado_sessao():
    padroes = {
        'logado': False,
        'usuario_id': None,
        'usuario_cod': "",
        'usuario_nome': "",
        'tipo_usuario': "comum",
        'franquias_permitidas': [],
        'em_verificacao_2fa': False,
        'codigo_2fa_esperado': "",
        'codigo_2fa_expira': None,
        'tentativas_2fa': 0,
        'canal_2fa': "",
        'dados_usuario_temp': {},
    }
    for chave, valor in padroes.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def carregar_franquias_usuario(usuario_id):
    """
    Franquias que o usuario pode ver, ja unificadas. Admin nao usa esta lista.

    O banco guarda os nomes como vieram da planilha, com a grade
    ("FRQ SBC SP R01 - MATRIZ"). A unificacao acontece na leitura para casar
    com a base de NPS, que tambem e unificada na carga -- assim nao e preciso
    migrar as linhas ja gravadas.
    """
    from franquias import unificar_lista
    df = run_query(
        "SELECT franquia FROM nps_usuario_franquias WHERE usuario_id = :uid ORDER BY franquia",
        {"uid": int(usuario_id)}, ttl=0
    )
    if df.empty:
        return []
    return unificar_lista(df['franquia'].astype(str).str.strip().tolist())


def _aplicar_login(row):
    """Preenche o session_state a partir de uma linha de nps_usuarios."""
    usuario_id = int(row['id'])
    tipo = str(row['tipo']).lower().strip()
    st.session_state.update({
        'logado': True,
        'usuario_id': usuario_id,
        'usuario_cod': row['usuario'],
        'usuario_nome': row['nome'],
        'tipo_usuario': tipo,
        'franquias_permitidas': [] if tipo in TIPOS_IRRESTRITOS else carregar_franquias_usuario(usuario_id),
        'em_verificacao_2fa': False,
        'codigo_2fa_esperado': "",
        'tentativas_2fa': 0,
        'dados_usuario_temp': {},
    })


def criar_sessao_persistente(usuario_id):
    token = str(uuid.uuid4())
    expira_em = datetime.now() + timedelta(hours=HORAS_SESSAO)
    with conn.session as s:
        s.execute(
            text("UPDATE nps_usuarios SET token_sessao = :t, token_expira_em = :exp, ultimo_acesso = NOW() WHERE id = :id"),
            {"t": token, "exp": expira_em, "id": int(usuario_id)}
        )
        s.commit()
    st.query_params["sessao"] = token


def verificar_sessao_automatica():
    """Reloga a partir do token na URL, evitando novo SMS a cada refresh."""
    if st.session_state.get('logado', False):
        return
    token_url = st.query_params.get("sessao")
    if not token_url:
        return
    try:
        df = run_query(
            "SELECT * FROM nps_usuarios WHERE token_sessao = :t AND token_expira_em > NOW() AND ativo = TRUE",
            {"t": token_url}, ttl=0
        )
        if not df.empty:
            _aplicar_login(df.iloc[0])
            st.rerun()
        else:
            st.query_params.clear()
    except Exception:
        pass


def realizar_logout():
    if st.session_state.get('usuario_id'):
        try:
            run_transaction(
                "UPDATE nps_usuarios SET token_sessao = NULL, token_expira_em = NULL WHERE id = :id",
                {"id": int(st.session_state['usuario_id'])}
            )
        except Exception:
            pass
    st.query_params.clear()
    st.session_state.clear()
    st.rerun()


# ==========================================================================
# LOGIN
# ==========================================================================
def validar_login(user_input, pass_input):
    """Retorna (ok, linha_ou_None, mensagem_de_erro)."""
    df = run_query(
        "SELECT * FROM nps_usuarios WHERE LOWER(usuario) = LOWER(:u)",
        {"u": str(user_input).strip()}, ttl=0
    )
    if df.empty:
        return False, None, "Usuário ou senha incorretos."
    linha = df.iloc[0]
    if not verificar_senha_hash(str(pass_input).strip(), linha['senha']):
        return False, None, "Usuário ou senha incorretos."
    if not bool(linha.get('ativo', True)):
        return False, None, "Acesso desativado. Procure o administrador."
    tel = str(linha.get('telefone') or '').strip()
    if len(formatar_telefone(tel)) < 12:
        return False, None, "Telefone não cadastrado. Peça ao administrador para cadastrar seu celular."
    return True, linha, ""


@st.cache_data
def _logo_base64(caminho="logo.png"):
    """Logo embutida em data URI, para poder usar dentro do HTML do formulario."""
    if not os.path.exists(caminho):
        return None
    with open(caminho, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _cabecalho_login(subtitulo):
    """Logo no lugar do titulo, com o nome do painel como subtitulo abaixo."""
    logo = _logo_base64()
    if logo:
        topo = (f"<img src='data:image/png;base64,{logo}' "
                f"style='max-width:230px;width:100%;height:auto;margin:0 auto 14px auto;display:block;'>")
    else:
        topo = "<h1 style='color:#0A2A66;font-weight:800;font-size:2.4rem;margin:0 0 6px 0;'>NPS</h1>"

    st.markdown(
        f"<div style='text-align:center;margin-bottom:20px;'>{topo}"
        f"<p style='color:#0A2A66;font-size:1.15rem;font-weight:700;margin:0;letter-spacing:.3px;'>NPS - Franquias</p>"
        f"<p style='color:#5A6B8C;font-size:.88rem;margin:6px 0 0 0;'>{subtitulo}</p>"
        f"</div>", unsafe_allow_html=True
    )


def tela_login():
    st.markdown("""
        <style>
        /* Tela de login sem as barras do Streamlit */
        [data-testid="stSidebar"], [data-testid="stHeader"],
        [data-testid="stToolbar"], [data-testid="stDecoration"],
        [data-testid="stStatusWidget"], #MainMenu, header, footer { display: none !important; }
        .stApp { background: linear-gradient(-45deg, #0A2A66, #1E5FCC, #3B82F6, #6baed6);
                 background-size: 400% 400%; animation: grad 15s ease infinite; }
        @keyframes grad { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
        .block-container { padding-top: 2.5rem !important; }
        [data-testid="stForm"] { background:#fff; padding:38px; border-radius:18px; box-shadow:0 10px 30px rgba(0,0,0,.25); }
        </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.write("")
        if st.session_state.get('em_verificacao_2fa', False):
            _form_2fa()
        else:
            _form_credenciais()


def _form_credenciais():
    with st.form("f_login"):
        _cabecalho_login("Acesse com seu usuário e senha.")
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        st.write("")
        if st.form_submit_button("ENTRAR", type="primary", use_container_width=True):
            ok, linha, erro = validar_login(u, p)
            if not ok:
                st.error(erro)
                return
            codigo = str(random.randint(100000, 999999))
            enviou, canal, info = enviar_codigo_2fa(linha['telefone'], codigo)
            if not enviou:
                st.error("Não foi possível enviar o código de verificação.")
                st.caption(f"Detalhe técnico: {info}")
                return
            st.session_state['em_verificacao_2fa'] = True
            st.session_state['codigo_2fa_esperado'] = codigo
            st.session_state['codigo_2fa_expira'] = datetime.now() + timedelta(minutes=10)
            st.session_state['tentativas_2fa'] = 0
            st.session_state['canal_2fa'] = canal
            st.session_state['dados_usuario_temp'] = linha.to_dict()
            st.rerun()

    st.write("")
    if st.button("Esqueci minha senha", type="secondary", use_container_width=True):
        modal_recuperar_senha()


def _form_2fa():
    dados = st.session_state.get('dados_usuario_temp', {})
    final_tel = str(dados.get('telefone', ''))[-4:]
    canal = st.session_state.get('canal_2fa', 'WhatsApp')
    with st.form("f_2fa"):
        _cabecalho_login(
            f"Verificação em 2 etapas<br>"
            f"Enviamos um código por <b>{canal}</b> para o número final <b>{final_tel}</b>."
        )
        codigo_digitado = st.text_input("Código de 6 dígitos", max_chars=6)
        if st.form_submit_button("VALIDAR ACESSO", type="primary", use_container_width=True):
            expira = st.session_state.get('codigo_2fa_expira')
            if expira and datetime.now() > expira:
                st.error("Código expirado. Volte e faça o login novamente.")
                return
            if st.session_state.get('tentativas_2fa', 0) >= 5:
                st.error("Muitas tentativas. Volte e faça o login novamente.")
                return
            if str(codigo_digitado).strip() == st.session_state.get('codigo_2fa_esperado'):
                _aplicar_login(dados)
                # Registra antes de abrir a sessão: se a gravação do token
                # falhar, o log da tentativa bem-sucedida de 2FA não se perde.
                registrar_log("Login", f"Usuario: {dados['usuario']} | canal 2FA: {canal}")
                criar_sessao_persistente(dados['id'])
                st.rerun()
            else:
                st.session_state['tentativas_2fa'] = st.session_state.get('tentativas_2fa', 0) + 1
                restantes = 5 - st.session_state['tentativas_2fa']
                st.error(f"Código incorreto. Tentativas restantes: {max(restantes, 0)}")

    if st.button("Voltar", type="secondary", use_container_width=True):
        st.session_state['em_verificacao_2fa'] = False
        st.session_state['codigo_2fa_esperado'] = ""
        st.session_state['dados_usuario_temp'] = {}
        st.rerun()


# ==========================================================================
# RECUPERACAO DE SENHA
# ==========================================================================
@st.dialog("Recuperar acesso")
def modal_recuperar_senha():
    st.write("Digite seu usuário. Enviaremos um link por SMS para redefinir a senha.")
    user_input = st.text_input("Usuário")
    if st.button("Enviar link", type="primary"):
        df = run_query(
            "SELECT * FROM nps_usuarios WHERE LOWER(usuario) = LOWER(:u)",
            {"u": str(user_input).strip()}, ttl=0
        )
        if df.empty:
            st.error("Usuário não encontrado.")
            return
        row = df.iloc[0]
        tel = str(row.get('telefone') or '')
        if len(formatar_telefone(tel)) < 12:
            st.error("Telefone não cadastrado. Procure o administrador.")
            return

        reset_token = str(uuid.uuid4())
        expiracao = datetime.now() + timedelta(minutes=15)
        try:
            run_transaction(
                "UPDATE nps_usuarios SET reset_token = :rt, reset_token_expira = :exp WHERE id = :id",
                {"rt": reset_token, "exp": expiracao, "id": int(row['id'])}
            )
            base = st.secrets.get("APP_URL", "").rstrip('/')
            link = f"{base}/?rt={reset_token}" if base else f"?rt={reset_token}"
            ok, det = enviar_sms(tel, f"Painel NPS: redefina sua senha (valido por 15 min): {link}")
            if ok:
                st.success("Link enviado por SMS. Verifique seu celular.")
                registrar_log("Solicitacao de reset", f"Usuario: {row['usuario']}")
                time.sleep(3)
                st.rerun()
            else:
                st.error(f"Erro ao enviar SMS: {det}")
        except Exception as e:
            st.error(f"Erro interno: {e}")


def tela_nova_senha_token(token_url):
    st.markdown("<h2 style='text-align:center;color:#0A2A66;'>Definir nova senha</h2>", unsafe_allow_html=True)
    df = run_query(
        "SELECT * FROM nps_usuarios WHERE reset_token = :rt AND reset_token_expira > NOW()",
        {"rt": token_url}, ttl=0
    )
    if df.empty:
        st.error("Este link é inválido ou já expirou.")
        if st.button("Voltar ao início"):
            st.query_params.clear()
            st.rerun()
        return

    usuario_id = int(df.iloc[0]['id'])
    st.info(f"Olá, {df.iloc[0]['nome']}. Defina sua nova senha abaixo.")
    with st.form("form_reset_final"):
        nova1 = st.text_input("Nova senha", type="password")
        nova2 = st.text_input("Confirme a senha", type="password")
        if st.form_submit_button("REDEFINIR SENHA", type="primary", use_container_width=True):
            if len(nova1) < 6:
                st.error("A senha deve ter ao menos 6 caracteres.")
            elif nova1 != nova2:
                st.error("As senhas não conferem.")
            else:
                run_transaction(
                    "UPDATE nps_usuarios SET senha = :s, reset_token = NULL, reset_token_expira = NULL WHERE id = :id",
                    {"s": gerar_hash(nova1), "id": usuario_id}
                )
                registrar_log("Senha redefinida", f"Usuario id: {usuario_id}")
                st.success("Senha alterada com sucesso. Redirecionando...")
                st.query_params.clear()
                time.sleep(2)
                st.rerun()


@st.dialog("Alterar minha senha")
def modal_alterar_senha():
    atual = st.text_input("Senha atual", type="password")
    nova1 = st.text_input("Nova senha", type="password")
    nova2 = st.text_input("Confirme a nova senha", type="password")
    if st.button("Salvar", type="primary"):
        df = run_query("SELECT senha FROM nps_usuarios WHERE id = :id",
                       {"id": int(st.session_state['usuario_id'])}, ttl=0)
        if df.empty or not verificar_senha_hash(atual, df.iloc[0]['senha']):
            st.error("Senha atual incorreta.")
            return
        if len(nova1) < 6:
            st.error("A nova senha deve ter ao menos 6 caracteres.")
            return
        if nova1 != nova2:
            st.error("As senhas não conferem.")
            return
        run_transaction("UPDATE nps_usuarios SET senha = :s WHERE id = :id",
                        {"s": gerar_hash(nova1), "id": int(st.session_state['usuario_id'])})
        registrar_log("Senha alterada", f"Usuario: {st.session_state['usuario_cod']}")
        st.success("Senha alterada. Faça login novamente.")
        time.sleep(2)
        realizar_logout()


# ==========================================================================
# GATE DE AUTENTICACAO
# ==========================================================================
def exigir_login():
    """
    Ponto de entrada. Retorna somente quando ha usuario autenticado;
    caso contrario renderiza a tela de login e interrompe o script.
    """
    # Injetado ANTES de qualquer acesso ao banco: senao o cabecalho e o
    # "Running..." do Streamlit aparecem durante a conexao, antes do CSS
    # da tela de login entrar em vigor. Depois do login, NPS_app.py devolve
    # o cabecalho.
    st.markdown("""
        <style>
        [data-testid="stHeader"], [data-testid="stToolbar"],
        [data-testid="stDecoration"], [data-testid="stStatusWidget"],
        #MainMenu, footer { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    iniciar_banco_dados()
    iniciar_estado_sessao()

    if "rt" in st.query_params:
        tela_nova_senha_token(st.query_params["rt"])
        st.stop()

    verificar_sessao_automatica()

    if not st.session_state.get('logado', False):
        tela_login()
        st.stop()


def _tipo_atual():
    return str(st.session_state.get('tipo_usuario', 'comum')).lower().strip()


def eh_admin():
    return _tipo_atual() == 'admin'


def eh_operacao():
    return _tipo_atual() == 'operacao'


def ve_todas_franquias():
    """admin e operacao enxergam a base inteira; comum so as franquias vinculadas."""
    return _tipo_atual() in TIPOS_IRRESTRITOS


def pode_editar_usuarios():
    """Somente admin altera cadastros. Operacao ve a aba Usuarios em leitura."""
    return _tipo_atual() == 'admin'


def rotulo_perfil():
    return ROTULO_TIPO.get(_tipo_atual(), 'Franquias vinculadas')
