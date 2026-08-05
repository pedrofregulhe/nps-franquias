import streamlit as st
from sqlalchemy import text
import pandas as pd
from datetime import datetime, timedelta
import time
import base64
import bcrypt
import requests
import re
import random
import string
import uuid

# --- CONFIGURAÇÕES GERAIS ---
st.set_page_config(
    page_title="Loja Culligan", 
    layout="wide", 
    page_icon="🎁",
    menu_items={} 
)

# --- CONEXÃO SQL (NEON) ---
conn = st.connection("postgresql", type="sql", pool_pre_ping=True, pool_recycle=300)

# --- ROBÔ DE ATUALIZAÇÃO DO BANCO (MIGRAÇÕES) ---
@st.cache_resource
def iniciar_banco_dados():
    with conn.session as s:
        try:
            # Colunas originais
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS valor_ponto FLOAT DEFAULT 0.50;"))
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS consentimento_lgpd BOOLEAN DEFAULT FALSE;"))
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS data_consentimento TIMESTAMP;"))
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS token_expira_em TIMESTAMP;"))
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS reset_token TEXT;"))
            s.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS reset_token_expira TIMESTAMP;"))
            
            s.commit()
        except Exception as e:
            print(f"Erro BD: {e}") 

iniciar_banco_dados()

# --- INICIALIZAÇÃO DA SESSÃO ---
if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'usuario_cod' not in st.session_state: st.session_state['usuario_cod'] = ""
if 'usuario_nome' not in st.session_state: st.session_state['usuario_nome'] = ""
if 'tipo_usuario' not in st.session_state: st.session_state['tipo_usuario'] = "comum"
if 'saldo_atual' not in st.session_state: st.session_state['saldo_atual'] = 0.0
if 'valor_ponto_usuario' not in st.session_state: st.session_state['valor_ponto_usuario'] = 0.50 
if 'admin_mode' not in st.session_state: st.session_state['admin_mode'] = True 
if 'supervisor_mode' not in st.session_state: st.session_state['supervisor_mode'] = True 
if 'lgpd_pendente' not in st.session_state: st.session_state['lgpd_pendente'] = False

if 'em_verificacao_2fa' not in st.session_state: st.session_state['em_verificacao_2fa'] = False
if 'codigo_2fa_esperado' not in st.session_state: st.session_state['codigo_2fa_esperado'] = ""
if 'dados_usuario_temp' not in st.session_state: st.session_state['dados_usuario_temp'] = {}

# --- CSS DINÂMICO ---
css_comum = """
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;800;900&display=swap');
    
    #MainMenu {visibility: hidden;}
    [data-testid="stHeader"] {display: none;}
    footer {visibility: hidden;}

    @keyframes gradient { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }

    h1, h2, h3, h4, h5, h6, p, a, li, button, input, select, textarea, label, .stMarkdown, .stText {
        font-family: 'Poppins', sans-serif !important; color: #31333F; 
    }
    
    .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }

    .header-style { background: linear-gradient(-45deg, #000428, #004e92, #2F80ED, #56CCF2); background-size: 400% 400% !important; animation: gradient 10s ease infinite !important; padding: 0 25px; border-radius: 12px; color: white !important; box-shadow: 0 4px 15px rgba(0,0,0,0.1); display: flex; flex-direction: column; justify-content: center; height: 110px !important; margin: 0 !important; }
    .header-style h2, .header-style p, .header-style span, .header-style div { color: white !important; }
    .header-style h2 { font-size: 20px !important; font-weight: 700 !important; margin: 0 !important; }
    .header-style p { font-size: 12px !important; line-height: 1.3 !important; opacity: 0.9 !important; margin: 2px 0 0 0 !important; }
    .header-style .saldo-label { font-size: 10px !important; font-weight: 600 !important; }
    .header-style .saldo-valor { font-size: 30px !important; font-weight: 900 !important; text-shadow: 0 2px 4px rgba(0,0,0,0.15); }

    div.stButton > button { border-radius: 8px !important; font-weight: 600 !important; width: 100%; border: none !important; }
    [data-testid="stTabs"] div.stButton > button { height: 45px !important; min-height: 45px !important; max-height: 45px !important; margin-top: auto !important; }
    [data-testid="stTabs"] button[kind="primary"] { background-color: #0066cc !important; color: white !important; }
    [data-testid="stTabs"] button[kind="primary"]:hover { background-color: #0052a3 !important; }
    [data-testid="stTabs"] button[kind="primary"] p { color: white !important; }
    [data-testid="stTabs"] button[kind="secondary"] { background-color: #ffffff !important; color: #003366 !important; border: 1px solid #e0e0e0 !important; }
    [data-testid="stTabs"] button[kind="secondary"]:hover { background-color: #f5f5f5 !important; }
    div[data-testid="column"] div.stButton > button[kind="secondary"] { background-color: #ffffff !important; color: #003366 !important; border: 2px solid #eef2f6 !important; height: 50px !important; min-height: 50px !important; }

    [data-testid="stImage"] img { height: 110px !important; object-fit: contain !important; border-radius: 10px; }
    [data-testid="stMetricValue"] { font-size: 2.2rem !important; }
    [data-testid="stMetricLabel"] { font-size: 1rem !important; }

    .rifa-card { border: 2px solid #FFD700; background: linear-gradient(to bottom right, #fffdf0, #ffffff); padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px; }
    .rifa-tag { background-color: #FFD700; color: #000; padding: 5px 15px; border-radius: 20px; font-weight: bold; font-size: 12px; margin-bottom: 10px; display: inline-block; }
    .winner-card { border: 2px solid #28a745; background: linear-gradient(to bottom right, #f0fff4, #ffffff); padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px; }
    .winner-tag { background-color: #28a745; color: #fff; padding: 5px 15px; border-radius: 20px; font-weight: bold; font-size: 12px; margin-bottom: 10px; display: inline-block; }


    @media only screen and (max-width: 600px) {
        .header-style { height: auto !important; padding: 15px !important; text-align: center !important; }
        div.stButton > button { height: 50px !important; }
    }
"""

if not st.session_state.get('logado', False):
    estilo_especifico = """
    .stApp { background: linear-gradient(-45deg, #000428, #004e92, #2F80ED, #56CCF2); background-size: 400% 400% !important; animation: gradient 15s ease infinite !important; }
    [data-testid="stForm"] { background-color: #ffffff; padding: 40px; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
    """
else:
    estilo_especifico = ".stApp { background-color: #f4f8fb; }"

st.markdown(f"<style>{css_comum} {estilo_especifico}</style>", unsafe_allow_html=True)

# --- FUNÇÕES BÁSICAS ---
def processar_link_imagem(url):
    url = str(url).strip()
    if "github.com" in url and "/blob/" in url: return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    if "drive.google.com" in url:
        if "id=" in url: return url
        try: file_id = url.split("/")[-2]; return f"https://drive.google.com/uc?export=view&id={file_id}"
        except: return url
    return url

def verificar_senha_hash(senha_digitada, hash_armazenado):
    try:
        if not hash_armazenado.startswith("$2b$"): return senha_digitada == hash_armazenado
        return bcrypt.checkpw(senha_digitada.encode('utf-8'), hash_armazenado.encode('utf-8'))
    except Exception: return False

def gerar_hash(senha):
    return bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def gerar_senha_aleatoria(tamanho=6):
    caracteres = string.ascii_uppercase + string.digits
    return ''.join(random.choice(caracteres) for _ in range(tamanho))

def formatar_telefone(tel):
    apenas_numeros = re.sub(r'\D', '', str(tel))
    if 10 <= len(apenas_numeros) <= 11: apenas_numeros = "55" + apenas_numeros
    return apenas_numeros

# --- GERENCIAMENTO DE SESSÃO ---
def criar_sessao_persistente(usuario_id):
    token = str(uuid.uuid4())
    expira_em = datetime.now() + timedelta(hours=24)
    with conn.session as s:
        s.execute(text("UPDATE usuarios SET token_sessao = :t, token_expira_em = :exp WHERE id = :id"), 
                  {"t": token, "exp": expira_em, "id": usuario_id})
        s.commit()
    st.query_params["sessao"] = token

def verificar_sessao_automatica():
    if st.session_state.get('logado', False): return
    token_url = st.query_params.get("sessao")
    if token_url:
        try:
            df = run_query("SELECT * FROM usuarios WHERE token_sessao = :t AND token_expira_em > NOW()", {"t": token_url}, ttl=0)
            if not df.empty:
                row = df.iloc[0]
                tem_lgpd = bool(row.get('consentimento_lgpd', False))
                st.session_state.update({
                    'logado': True,
                    'usuario_cod': row['usuario'],
                    'usuario_nome': row['nome'],
                    'tipo_usuario': str(row['tipo']).lower().strip(),
                    'saldo_atual': float(row['saldo']),
                    'valor_ponto_usuario': float(row.get('valor_ponto', 0.50) or 0.50),
                    'lgpd_pendente': not tem_lgpd
                })
                st.rerun()
            else:
                if st.query_params.get("sessao"):
                    st.query_params.clear()
        except Exception:
            pass

def realizar_logout():
    if st.session_state.get('usuario_cod'):
        with conn.session as s:
            s.execute(text("UPDATE usuarios SET token_sessao = NULL WHERE usuario = :u"), {"u": st.session_state.usuario_cod})
            s.commit()
    st.query_params.clear()
    st.session_state.clear()
    st.rerun()

# --- FUNÇÕES DE ENVIO ---
def enviar_sms(telefone, mensagem_texto):
    try:
        base_url = st.secrets["INFOBIP_BASE_URL"].rstrip('/')
        api_key = st.secrets["INFOBIP_API_KEY"]
        url = f"{base_url}/sms/2/text/advanced"
        tel_final = formatar_telefone(telefone)
        if len(tel_final) < 12: return False, f"Num Inválido: {tel_final}", "CLIENT_ERROR"
        payload = { "messages": [ { "from": "InfoSMS", "destinations": [{"to": tel_final}], "text": mensagem_texto } ] }
        headers = { "Authorization": f"App {api_key}", "Content-Type": "application/json", "Accept": "application/json" }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code not in [200, 201]: return False, f"Erro SMS {response.status_code}: {response.text}", str(response.status_code)
        return True, "SMS Enviado", str(response.status_code)
    except Exception as e: return False, f"Erro SMS Exception: {str(e)}", "EXCEPTION"

def enviar_whatsapp_template(telefone, parametros, nome_template="atualizar_saldo_pedidos_lojinha"):
    try:
        base_url = st.secrets["INFOBIP_BASE_URL"].rstrip('/')
        api_key = st.secrets["INFOBIP_API_KEY"]
        sender = st.secrets["INFOBIP_SENDER"]
        url = f"{base_url}/whatsapp/1/message/template"
        tel_final = formatar_telefone(telefone)
        if len(tel_final) < 12: return False, f"Número inválido: {tel_final}", "CLIENT_ERROR"
        # Idioma deve bater EXATAMENTE com o registrado no Infobip para cada template:
        # "Portuguese (POR)" = "pt_PT" | "Portuguese Brazil" = "pt_BR"
        idiomas_por_template = { "atualizar_saldo_pedidos_lojinha": "pt_PT" }
        idioma = idiomas_por_template.get(nome_template, "pt_BR")
        payload = { "messages": [ { "from": sender, "to": tel_final, "content": { "templateName": nome_template, "templateData": { "body": { "placeholders": [str(p) for p in parametros] } }, "language": idioma } } ] }
        headers = { "Authorization": f"App {api_key}", "Content-Type": "application/json", "Accept": "application/json" }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code not in [200, 201]: return False, f"Erro API {response.status_code}: {response.text}", str(response.status_code)
        # IMPORTANTE: o Infobip retorna HTTP 200 mesmo quando a mensagem é REJEITADA.
        # O status real de cada mensagem vem no corpo da resposta (messages[0].status).
        try:
            dados_resp = response.json()
            msg_status = dados_resp.get("messages", [{}])[0].get("status", {})
            grupo = str(msg_status.get("groupName", "")).upper()
            if grupo in ("REJECTED", "UNDELIVERABLE"):
                detalhe = msg_status.get("description") or msg_status.get("name") or "Rejeitado pelo Infobip"
                return False, f"Rejeitado pelo Infobip: {detalhe}", grupo
            return True, f"Aceito pelo Infobip ({grupo or 'PENDING'})", str(response.status_code)
        except Exception:
            return True, "Enviado (status do corpo não verificado)", str(response.status_code)
    except Exception as e: return False, f"Erro Conexão: {str(e)}", "EXCEPTION"

# --- BANCO DE DADOS ---
def run_query(query_str, params=None, ttl="5m"):
    try:
        return conn.query(query_str, params=params, ttl=ttl)
    except Exception:
        st.cache_data.clear()
        try:
            conn.reset() 
            return conn.query(query_str, params=params, ttl=ttl)
        except Exception:
            st.error("Desculpe, o banco de dados está se reconectando. Por favor, atualize a página.")
            return pd.DataFrame()

def run_transaction(query_str, params=None):
    with conn.session as s: s.execute(text(query_str), params if params else {}); s.commit()

def registrar_log(acao, detalhes):
    try:
        resp = st.session_state.get('usuario_nome', 'Sistema')
        run_transaction("INSERT INTO logs (data, responsavel, acao, detalhes) VALUES (NOW(), :resp, :acao, :det)", {"resp": resp, "acao": acao, "det": detalhes})
    except Exception as e: print(f"Erro log: {e}")

# --- LÓGICA DE NEGÓCIO ---
def validar_login(user_input, pass_input):
    df = run_query("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": user_input.strip()}, ttl=0)
    if df.empty: return False, None, None, 0, None, None, 0.50, False
    linha = df.iloc[0]
    if verificar_senha_hash(pass_input.strip(), linha['senha']):
        v_ponto = float(linha.get('valor_ponto', 0.50) or 0.50)
        tem_lgpd = bool(linha.get('consentimento_lgpd', False))
        return True, linha['nome'], str(linha['tipo']).lower().strip(), float(linha['saldo']), str(linha['telefone']), int(linha['id']), v_ponto, tem_lgpd
    return False, None, None, 0, None, None, 0.50, False, False

def salvar_venda(usuario_cod, item_nome, custo, email_contato, telefone_resgate):
    try:
        user_df = run_query("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": usuario_cod}, ttl=0)
        
        if user_df.empty: 
            st.error("Erro interno: Cadastro não localizado para o resgate.")
            return False
            
        if float(user_df.iloc[0]['saldo']) < custo: st.error("Saldo insuficiente."); return False
        with conn.session as s:
            s.execute(text("UPDATE usuarios SET saldo = saldo - :custo WHERE LOWER(usuario) = LOWER(:u)"), {"custo": custo, "u": usuario_cod})
            s.execute(text("INSERT INTO vendas (data, usuario, item, valor, status, email, nome_real, telefone) VALUES (NOW(), :u, :item, :valor, 'Pendente', :email, :nome, :tel)"),
                {"u": usuario_cod, "item": item_nome, "valor": custo, "email": email_contato, "nome": user_df.iloc[0]['nome'], "tel": telefone_resgate})
            s.commit()
        registrar_log("Resgate", f"Usuário: {user_df.iloc[0]['nome']} | Item: {item_nome}")
        st.session_state['saldo_atual'] -= custo
        st.cache_data.clear() 
        return True
    except Exception as e: st.error(f"Erro: {e}"); return False

def comprar_ticket_rifa(rifa_id, custo, usuario_cod):
    try:
        user_df = run_query("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": usuario_cod}, ttl=0)
        if user_df.empty: return False, "Usuário não encontrado"
        custo_real = float(custo)
        if float(user_df.iloc[0]['saldo']) < custo_real: return False, "Saldo insuficiente"
        with conn.session as s:
            s.execute(text("UPDATE usuarios SET saldo = saldo - :custo WHERE LOWER(usuario) = LOWER(:u)"), 
                      {"custo": custo_real, "u": usuario_cod})
            s.execute(text("INSERT INTO rifa_tickets (rifa_id, usuario) VALUES (:rid, :u)"), 
                      {"rid": int(rifa_id), "u": usuario_cod})
            s.commit()
        st.session_state['saldo_atual'] -= custo_real
        registrar_log("Rifa", f"Comprou ticket rifa {rifa_id}")
        st.cache_data.clear() 
        return True, "Ticket comprado com sucesso!"
    except Exception as e: return False, f"Erro: {str(e)}"

# --- CADASTRO E DISTRIBUIÇÃO ---
def cadastrar_novo_usuario(usuario, senha, nome, saldo, tipo, telefone, valor_ponto=0.50, consentimento_lgpd=False):
    usuario = usuario.strip()
    try:
        df = run_query("SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": usuario}, ttl=0)
        if not df.empty: return False, "Usuário já existe!"
        
        data_cons = datetime.now() if consentimento_lgpd else None

        run_transaction(
            "INSERT INTO usuarios (usuario, senha, nome, saldo, pontos_historico, tipo, telefone, valor_ponto, consentimento_lgpd, data_consentimento) VALUES (:u, :s, :n, :bal, :bal, :t, :tel, :vp, :lgpd, :dt_lgpd)",
            {"u": usuario, "s": gerar_hash(senha), "n": nome, "bal": saldo, "t": tipo, "tel": formatar_telefone(telefone), "vp": valor_ponto, "lgpd": consentimento_lgpd, "dt_lgpd": data_cons}
        )
        registrar_log("Novo Cadastro", f"Criou usuário: {usuario}")
        return True, "Cadastrado com sucesso!"
    except Exception as e: return False, f"Erro: {str(e)}"

def distribuir_pontos_multiplos(lista_usuarios, quantidade):
    try:
        if "Todos" in lista_usuarios:
            run_transaction("UPDATE usuarios SET saldo = saldo + :q, pontos_historico = COALESCE(pontos_historico, 0) + :q WHERE tipo NOT IN ('admin', 'staff', 'supervisor')", {"q": quantidade})
            msg = f"Adicionou {quantidade} pts para TODOS (exceto staff/admin/supervisor)."
        else:
            with conn.session as s:
                s.execute(
                    text("UPDATE usuarios SET saldo = saldo + :q, pontos_historico = COALESCE(pontos_historico, 0) + :q WHERE usuario IN :users"),
                    {"q": quantidade, "users": tuple(lista_usuarios)}
                )
                s.commit()
            msg = f"Adicionou {quantidade} pts para {len(lista_usuarios)} usuários."
        registrar_log("Distribuição Pontos", msg)
        return True
    except Exception as e: return False

# --- MODAIS E DIÁLOGOS ---
@st.dialog("🔒 Termos de Uso e Privacidade (LGPD)")
def modal_consentimento_lgpd():
    st.markdown("""
    ### Política de Privacidade e Proteção de Dados
    
    Para continuar utilizando a **Lojinha Culli's**, precisamos do seu consentimento para o tratamento dos seus dados pessoais, em conformidade com a Lei Geral de Proteção de Dados (LGPD - Lei nº 13.709/2018).

    **1. Dados Coletados:**
    * Nome completo, Login e Telefone (WhatsApp).
    * Histórico de transações (pontos ganhos e resgates).
    * Logs de acesso e endereço IP (para segurança).

    **2. Finalidade do Tratamento:**
    * Gestão do programa de recompensas e entrega de prêmios.
    * Comunicação sobre status de pedidos via WhatsApp/SMS.
    * Auditoria e prevenção de fraudes.

    **3. Seus Direitos:**
    * Você pode solicitar o acesso, correção ou exclusão dos seus dados a qualquer momento entrando em contato com a administração.
    * A exclusão dos dados implicará no cancelamento da conta e perda dos pontos acumulados.

    **4. Segurança:**
    * Os dados podem ser compartilhados com operadores de tecnologia necessários para execução do serviço (ex: envio de SMS/WhatsApp), respeitando a LGPD e não são compartilhados com terceiros para fins publicitários.

    ---
    Ao clicar em **"Li e Aceito"**, você declara estar ciente e de acordo com os termos acima.
    """)
    
    if st.button("✅ LI E ACEITO OS TERMOS", type="primary", use_container_width=True):
        try:
            u_cod = st.session_state.get('usuario_cod')
            if u_cod:
                with conn.session as s:
                    s.execute(text("UPDATE usuarios SET consentimento_lgpd = TRUE, data_consentimento = NOW() WHERE usuario = :u"), {"u": u_cod})
                    s.commit()
                st.session_state['lgpd_pendente'] = False
                st.cache_data.clear()
                st.success("Consentimento registrado com sucesso!")
                time.sleep(1)
                st.rerun()
        except Exception as e:
            st.error(f"Erro ao registrar: {e}")

@st.dialog("💾 Confirmação de Sistema")
def modal_sucesso_salvamento(detalhes):
    st.success("As alterações foram gravadas no banco de dados!")
    st.code(f"LOG: {detalhes}\nTIMESTAMP: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", language="sql")
    if st.button("Fechar Janela", type="primary"):
        st.rerun()

@st.dialog("🔐 Alterar Senha")
def abrir_modal_senha(usuario_cod):
    n = st.text_input("Nova Senha", type="password"); c = st.text_input("Confirmar", type="password")
    if st.button("Salvar Senha", type="primary"):
        if n == c and n:
            run_transaction("UPDATE usuarios SET senha = :s WHERE LOWER(usuario) = LOWER(:u)", {"s": gerar_hash(n), "u": usuario_cod})
            registrar_log("Senha Alterada", f"Usuário: {usuario_cod}")
            st.success("Sucesso!"); time.sleep(1); st.session_state['logado'] = False; st.rerun()

@st.dialog("👤 Meu Perfil")
def abrir_modal_perfil(usuario_cod):
    df_user = run_query("SELECT nome, telefone FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": usuario_cod}, ttl=0)
    
    if df_user.empty:
        st.error("Erro ao carregar dados do usuário.")
        return
        
    nome_atual = df_user.iloc[0]['nome']
    tel_atual = str(df_user.iloc[0]['telefone'])
    
    with st.form("form_perfil"):
        st.write("Atualize seus dados de contato abaixo:")
        novo_nome = st.text_input("Nome Completo", value=nome_atual)
        novo_telefone = st.text_input("Telefone / WhatsApp (DDD+Número)", value=tel_atual)
        
        st.divider()
        st.write("🔐 **Alterar Senha (Opcional)**")
        st.caption("Deixe em branco se não quiser alterar sua senha atual.")
        n = st.text_input("Nova Senha", type="password")
        c = st.text_input("Confirmar Nova Senha", type="password")
        
        if st.form_submit_button("💾 Salvar Alterações", type="primary", use_container_width=True):
            tel_formatado = formatar_telefone(novo_telefone)
            if len(tel_formatado) < 12:
                st.error("Telefone inválido! Digite com o DDD.")
                return
            
            query = "UPDATE usuarios SET nome = :n, telefone = :t"
            params = {"n": novo_nome, "t": tel_formatado, "u": usuario_cod}
            
            if n or c:
                if n != c:
                    st.error("As senhas não coincidem!")
                    return
                if len(n) < 4:
                    st.error("A nova senha deve ter pelo menos 4 caracteres.")
                    return
                query += ", senha = :s"
                params["s"] = gerar_hash(n)
                
            query += " WHERE LOWER(usuario) = LOWER(:u)"
            
            try:
                run_transaction(query, params)
                registrar_log("Perfil Atualizado", f"Usuário: {usuario_cod} alterou seus dados de perfil.")
                st.session_state['usuario_nome'] = novo_nome 
                st.success("Perfil atualizado com sucesso!")
                time.sleep(1.5)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao atualizar o perfil: {e}")

@st.dialog("🔑 Recuperar Acesso")
def enviar_link_recuperacao():
    st.write("Digite seu login. Enviaremos um link seguro via SMS para redefinir sua senha.")
    user_input = st.text_input("Login (Usuário)")
    
    if st.button("Enviar Link de Redefinição", type="primary"):
        df = run_query("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": user_input.strip()}, ttl=0)
        if df.empty:
            st.error("Usuário não encontrado.")
            return

        row = df.iloc[0]
        tel = str(row['telefone'])
        reset_token = str(uuid.uuid4())
        expiracao = datetime.now() + timedelta(minutes=15)
        
        try:
            with conn.session as s:
                s.execute(text("UPDATE usuarios SET reset_token = :rt, reset_token_expira = :exp WHERE id = :id"), 
                          {"rt": reset_token, "exp": expiracao, "id": int(row['id'])})
                s.commit()
            
            link_completo = f"https://lojinha-culligan.streamlit.app/?rt={reset_token}"
            mensagem = f"Culli: Para redefinir sua senha, acesse o link (valido por 15 min): {link_completo}"
            
            ok, det, cod = enviar_sms(tel, mensagem)
            
            if ok:
                st.success("Link enviado por SMS! Verifique seu celular.")
                registrar_log("Solicitação Reset", f"Usuário: {row['usuario']}")
                time.sleep(3); st.rerun()
            else:
                st.error(f"Erro ao enviar SMS: {det}")
        except Exception as e:
            st.error(f"Erro interno: {e}")

def tela_nova_senha_token(token_url):
    st.markdown("""<div style="text-align: center; margin-bottom: 20px;"><h2 style="color: #003366;">🔐 Nova Senha</h2><p>Defina sua nova senha de acesso.</p></div>""", unsafe_allow_html=True)
    
    try:
        df = run_query("SELECT * FROM usuarios WHERE reset_token = :rt AND reset_token_expira > NOW()", {"rt": token_url}, ttl=0)
        if df.empty:
            st.error("🚫 Este link é inválido ou já expirou.")
            if st.button("Voltar ao Início"):
                st.query_params.clear()
                st.rerun()
            return

        usuario_id = int(df.iloc[0]['id'])
        nome_user = df.iloc[0]['nome']
        
        st.info(f"Olá, **{nome_user}**! Digite sua nova senha abaixo.")
        
        with st.form("form_reset_final"):
            nova1 = st.text_input("Nova Senha", type="password")
            nova2 = st.text_input("Confirme a Senha", type="password")
            
            if st.form_submit_button("REDEFINIR SENHA", type="primary", use_container_width=True):
                if nova1 == nova2 and len(nova1) >= 4:
                    senha_hash = gerar_hash(nova1)
                    with conn.session as s:
                        s.execute(text("UPDATE usuarios SET senha = :s, reset_token = NULL, reset_token_expira = NULL WHERE id = :id"), 
                                  {"s": senha_hash, "id": usuario_id})
                        s.commit()
                    st.success("✅ Senha alterada com sucesso! Você será redirecionado.")
                    st.query_params.clear()
                    time.sleep(3)
                    st.rerun()
                else:
                    st.error("As senhas não coincidem ou são muito curtas.")
                    
    except Exception as e:
        st.error(f"Erro ao validar token: {e}")

@st.dialog("🎁 Confirmar Resgate")
def confirmar_resgate_dialog(item_nome, custo, usuario_cod):
    st.write(f"Resgatando: **{item_nome}** por **{custo} pts**.")
    with st.form("form_resgate"):
        email = st.text_input("E-mail:", placeholder="exemplo@email.com")
        tel = st.text_input("WhatsApp (DDD+Num):", placeholder="Ex: 34999998888")
        if st.form_submit_button("CONFIRMAR", type="primary", use_container_width=True):
            if "@" not in email: st.error("E-mail inválido."); return
            if len(formatar_telefone(tel)) < 12: st.error("Telefone inválido!"); return
            if salvar_venda(usuario_cod, item_nome, custo, email, formatar_telefone(tel)):
                st.balloons(); st.success("Sucesso!"); time.sleep(2); st.rerun()

@st.dialog("🎟️ Comprar Ticket Rifa")
def confirmar_compra_ticket(rifa_id, item_nome, custo, usuario_cod):
    st.write(f"Você está comprando um ticket para sortear: **{item_nome}**")
    st.write(f"Custo: **{custo} pts**")
    st.info("Quanto mais tickets comprar, maior a chance de ganhar!")
    if st.button("CONFIRMAR COMPRA", type="primary", use_container_width=True):
        ok, msg = comprar_ticket_rifa(rifa_id, custo, usuario_cod)
        if ok: st.balloons(); st.success(msg); time.sleep(2); st.rerun()
        else: st.error(msg)

@st.dialog("🎉 TEMOS UM VENCEDOR!")
def mostrar_vencedor_dialog(nome_vencedor, usuario_vencedor, nome_premio, imagem_premio):
    st.balloons()
    if imagem_premio: st.image(processar_link_imagem(imagem_premio), width=300)
    st.markdown(f"<h2 style='text-align:center; color:#28a745;'>{nome_vencedor}</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center;'>({usuario_vencedor})</p>", unsafe_allow_html=True)
    st.success(f"Parabéns! Você ganhou: {nome_premio}")
    st.info("O prêmio já foi adicionado aos seus pedidos.")

@st.dialog("🔍 Detalhes do Produto")
def ver_detalhes_produto(item, imagem, custo, descricao):
    st.image(processar_link_imagem(imagem), use_container_width=True)
    st.markdown(f"## {item}")
    st.markdown(f"#### 💎 Valor: **{custo} pts**")
    st.divider()
    st.write("### 📝 Descrição")
    if descricao and str(descricao).lower() != "none" and len(str(descricao)) > 3: st.write(descricao)
    else: st.caption("Sem descrição adicional para este item.")
    st.divider()
    st.info("ℹ️ **Informações de Entrega:**\nEste item será enviado para o endereço ou contato cadastrado. O prazo de processamento é de até 5 dias úteis.")

@st.dialog("🚀 Confirmar e Processar Envios")
def processar_envios_dialog(df_selecionados, tipo_envio="vendas"):
    st.write(f"Destinatários selecionados: **{len(df_selecionados)}**")
    
    st.markdown("##### 📡 Canais de Envio:")
    c1, c2 = st.columns(2)
    with c1: usar_zap = st.toggle("WhatsApp", value=True)
    with c2: usar_sms = st.toggle("SMS", value=True)
    
    invalidos = 0
    for _, row in df_selecionados.iterrows():
        if len(formatar_telefone(row['telefone'])) < 12: invalidos += 1
    if invalidos > 0:
        st.warning(f"⚠️ Atenção: {invalidos} números parecem inválidos.")

    st.markdown("---")
    
    if st.button("CONFIRMAR E DISPARAR", type="primary", use_container_width=True):
        if not usar_zap and not usar_sms:
            st.error("Selecione pelo menos um canal de envio.")
            return

        logs_envio = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(df_selecionados)
        
        for i, (index, row) in enumerate(df_selecionados.iterrows()):
            status_text.text(f"Processando {i+1}/{total}: {row.get('nome', '')}...")
            tel = str(row['telefone'])
            
            # Separação clara das variáveis por tipo de envio
            if tipo_envio == "vendas": 
                nome = str(row['nome_real'] or row['usuario'])
                var1 = str(row['item'])
                var2 = str(row['codigo_vale'])
            else: 
                nome = str(row['nome'])
                # Convertido para int para remover formatações com vírgula/ponto que o Infobip pode rejeitar
                var1 = str(int(float(row['saldo']))) 
                var2 = ""
            
            if usar_zap:
                if len(formatar_telefone(tel)) >= 12:
                    # Lógica de disparo isolada para garantir que o template correto seja chamado
                    if tipo_envio == "vendas":
                        ok, det, cod = enviar_whatsapp_template(tel, [nome, var1, var2], "atualizar_envio_pedidos")
                    else:
                        ok, det, cod = enviar_whatsapp_template(tel, [nome, var1], "atualizar_saldo_pedidos_lojinha")
                        
                    logs_envio.append({"Nome": nome, "Tel": tel, "Canal": "WhatsApp", "Status": "✅ OK" if ok else "❌ Erro", "Detalhe API": det})
                else: 
                    logs_envio.append({"Nome": nome, "Tel": tel, "Canal": "WhatsApp", "Status": "⚠️ Ignorado", "Detalhe API": "Número Inválido"})
            
            if usar_sms:
                if len(formatar_telefone(tel)) >= 12:
                    if tipo_envio == "vendas":
                        texto = f"Olá {nome}, seu resgate de {var1} foi liberado! Cód: {var2}."
                    else:
                        texto = f"Lojinha Culli: Olá {nome}, sua pontuação foi atualizada e seu saldo atual é de {var1}. Acesse o site e realize a troca: https://lojinha-culligan.streamlit.app/"
                        
                    ok, det, cod = enviar_sms(tel, texto)
                    logs_envio.append({"Nome": nome, "Tel": tel, "Canal": "SMS", "Status": "✅ OK" if ok else "❌ Erro", "Detalhe API": det})
                else: 
                    logs_envio.append({"Nome": nome, "Tel": tel, "Canal": "SMS", "Status": "⚠️ Ignorado", "Detalhe API": "Número Inválido"})
            
            progress_bar.progress((i + 1) / total)
        
        progress_bar.empty()
        status_text.success("Processamento Finalizado!")
        sucessos = len([x for x in logs_envio if "OK" in x['Status']])
        
        c1, c2 = st.columns(2)
        c1.metric("✅ Sucessos", sucessos)
        c2.metric("❌ Falhas", len(logs_envio) - sucessos)
        
        registrar_log("Disparo em Massa", f"Tipo: {tipo_envio} | Qtd: {total}")
        
        with st.expander("📄 Ver Log Detalhado"):
            st.dataframe(pd.DataFrame(logs_envio), use_container_width=True)
            
        st.download_button(label="📥 Baixar CSV", data=pd.DataFrame(logs_envio).to_csv(index=False).encode('utf-8'), file_name='log_envio.csv', mime='text/csv')

# --- TELAS ---
def tela_login():
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.write("") 
        if st.session_state.get('em_verificacao_2fa', False):
            with st.form("f_2fa"):
                st.markdown("""<div style="text-align: center; margin-bottom: 20px;"><h2 style="color: #003366;">🔒 Segurança</h2><p>Enviamos um código SMS para o final <b>...{}</b></p></div>""".format(str(st.session_state.dados_usuario_temp.get('telefone', ''))[-4:]), unsafe_allow_html=True)
                codigo_digitado = st.text_input("Digite o Código de 6 dígitos", max_chars=6, help="Verifique seu SMS")
                if st.form_submit_button("VALIDAR ACESSO", type="primary", use_container_width=True):
                    if codigo_digitado == st.session_state.codigo_2fa_esperado:
                        dados = st.session_state.dados_usuario_temp
                        tem_lgpd = st.session_state.get('temp_lgpd_status', False) 
                        
                        st.session_state.update({
                            'logado': True, 
                            'usuario_cod': dados['usuario'], 
                            'usuario_nome': dados['nome'], 
                            'tipo_usuario': dados['tipo'], 
                            'saldo_atual': dados['saldo'], 
                            'valor_ponto_usuario': dados.get('valor_ponto', 0.50), 
                            'em_verificacao_2fa': False, 
                            'dados_usuario_temp': {},
                            'lgpd_pendente': not tem_lgpd
                        })
                        criar_sessao_persistente(dados['id']); st.rerun()
                    else: st.error("Código incorreto. Tente novamente.")
            if st.button("⬅️ Voltar", type="secondary", use_container_width=True): st.session_state.em_verificacao_2fa = False; st.session_state.dados_usuario_temp = {}; st.rerun()
        else:
            with st.form("f_login"):
                st.markdown("""<div style="text-align: center; margin-bottom: 20px;"><h1 style="color: #003366; font-weight: 900; font-size: 2.8rem; margin: 0; margin-bottom: -15px; line-height: 1;">Lojinha Culli's</h1><p style="color: #555555; font-size: 0.9rem; line-height: 1.2; font-weight: 400; margin: 0; margin-top: 0px;">Realize seu login para resgatar seus pontos<br>e acompanhar seus pedidos.</p></div>""", unsafe_allow_html=True)
                u = st.text_input("Usuário"); s = st.text_input("Senha", type="password")
                st.write("") 
                if st.form_submit_button("ENTRAR", type="primary", use_container_width=True):
                    ok, n, t, sld, tel_completo, uid, v_ponto, tem_lgpd = validar_login(u, s)
                    if ok:
                        codigo = str(random.randint(100000, 999999))
                        msg_2fa = f"Seu codigo de acesso Culli: {codigo}"
                        enviou, info, _ = enviar_sms(tel_completo, msg_2fa)
                        if enviou:
                            st.session_state.em_verificacao_2fa = True
                            st.session_state.codigo_2fa_esperado = codigo
                            
                            st.session_state.dados_usuario_temp = {'usuario': u.strip(), 'nome': n, 'tipo': t, 'saldo': sld, 'telefone': tel_completo, 'id': uid, 'valor_ponto': v_ponto}
                            
                            st.session_state['temp_lgpd_status'] = tem_lgpd 
                            st.rerun()
                        else: st.error(f"Erro no envio do SMS: {info}. Verifique se o telefone está correto no cadastro.")
                    else: st.toast("Usuário ou senha incorretos", icon="❌")
            st.write(""); c_esqueceu, c_primeiro = st.columns(2)
            with c_esqueceu:
                if st.button("Esqueci a senha", type="secondary", use_container_width=True): enviar_link_recuperacao()
            with c_primeiro:
                if st.button("Primeiro Acesso?", type="secondary", use_container_width=True): enviar_link_recuperacao()

def tela_admin():
    st.subheader("🛠️ Painel Admin")
    t1, t2, t3, t4, t5 = st.tabs(["📊 Entregas & WhatsApp", "👥 Usuários & Saldos", "🎁 Prêmios", "🛠️ Logs", "🎟️ Sorteio"])
    
    with t1:
        df_v = run_query("SELECT * FROM vendas ORDER BY id DESC")
        if not df_v.empty:
            lista_status = df_v['status'].dropna().unique().tolist()
            filtro_status = st.multiselect("🔍 Filtrar por Status:", options=lista_status, placeholder="Selecione para filtrar (Vazio = Todos)")
            if filtro_status: df_v = df_v[df_v['status'].isin(filtro_status)]
            if "Enviar" not in df_v.columns: df_v.insert(0, "Enviar", False)
            
            edit_v = st.data_editor(df_v, use_container_width=True, hide_index=True, key="ed_vendas", column_config={"Enviar": st.column_config.CheckboxColumn("Enviar?", default=False), "recebido_user": st.column_config.CheckboxColumn("Recebido pelo Usuário?", disabled=True)})
            
            st.markdown("<br>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
            with c2:
                if st.button("💾 Salvar Tabela", use_container_width=True, key="btn_save_vendas"):
                    st.cache_data.clear() 
                    try:
                        with conn.session as s:
                            for i, row in edit_v.iterrows():
                                s.execute(text("UPDATE vendas SET item=:item, valor=:valor, codigo_vale=:c, status=:st, nome_real=:n, telefone=:t, email=:e WHERE id=:id"), {"item": str(row['item']), "valor": float(row['valor']), "c": str(row['codigo_vale']), "st": str(row['status']), "n": str(row['nome_real']), "t": str(row['telefone']), "e": str(row.get('email', '')), "id": int(row['id'])})
                            s.commit()
                        registrar_log("Admin", "Editou vendas"); modal_sucesso_salvamento(f"Tabela Vendas atualizada. {len(edit_v)} registros processados.")
                    except Exception as e: st.error(f"Erro ao salvar: {e}")
            with c3:
                if st.button("📤 Enviar Selecionados", type="primary", use_container_width=True):
                    sel = edit_v[edit_v['Enviar'] == True]
                    if sel.empty: st.warning("Ninguém selecionado.")
                    else: processar_envios_dialog(sel, "vendas")
                    
    with t2:
        with st.expander("💎 Configurar Valor do Ponto Individualizado"):
            df_users_list = run_query("SELECT id, usuario, nome, valor_ponto FROM ORDER BY nome")
            if not df_users_list.empty:
                opcoes_user = {f"{row['nome']} ({row['usuario']})": row['id'] for i, row in df_users_list.iterrows()}
                user_selecionado_chave = st.selectbox("Selecione o Usuário:", list(opcoes_user.keys()))
                user_id_sel = opcoes_user[user_selecionado_chave]
                valor_atual = df_users_list[df_users_list['id'] == user_id_sel]['valor_ponto'].iloc[0]
                if pd.isna(valor_atual): valor_atual = 0.50
                novo_valor_ponto = st.number_input(f"Valor do Ponto para {user_selecionado_chave} (R$)", value=float(valor_atual), step=0.01, format="%.2f")
                if st.button("💾 Salvar Valor Personalizado", type="primary"):
                    try:
                        run_transaction("UPDATE usuarios SET valor_ponto = :vp WHERE id = :id", {"vp": novo_valor_ponto, "id": user_id_sel})
                        st.cache_data.clear(); modal_sucesso_salvamento(f"Usuário {user_id_sel} atualizado. Novo valor ponto: {novo_valor_ponto}")
                    except Exception as e: st.error(f"Erro: {e}")
                    
        with st.expander("➕ Cadastrar Novo Usuário"):
            with st.form("form_novo"):
                c_n1, c_n2 = st.columns(2)
                u = c_n1.text_input("Usuário"); s = c_n2.text_input("Senha"); n = c_n1.text_input("Nome"); t = c_n2.text_input("Telefone")
                bal = c_n1.number_input("Saldo", step=100.0); tp = c_n2.selectbox("Tipo", ["comum", "admin", "staff", "supervisor"]); vp = c_n1.number_input("Valor do Ponto (R$)", value=0.50, step=0.01)
                
                lgpd = st.checkbox("Forçar aceite LGPD? (Deixe vazio para o usuário aceitar no login)", value=False)
                
                if st.form_submit_button("Cadastrar"):
                    ok, msg = cadastrar_novo_usuario(u, s, n, bal, tp, t, vp, lgpd)
                    if ok: st.cache_data.clear(); modal_sucesso_salvamento(f"Novo usuário cadastrado: {u}"); 
                    else: st.error(msg)
            
            st.markdown("---")
            st.markdown("##### 📥 Cadastro em Lote via Excel")
            st.info("O arquivo .xlsx deve conter exatamente as colunas: **usuario, senha, nome, saldo, tipo, telefone, valor_ponto, consentimento_lgpd**")
            arquivo_excel = st.file_uploader("Upload de Planilha", type=["xlsx"], key="up_users")
            if arquivo_excel:
                if st.button("🚀 Processar Cadastros", type="primary"):
                    try:
                        df_upload = pd.read_excel(arquivo_excel)
                        colunas_req = ['usuario', 'senha', 'nome', 'saldo', 'tipo', 'telefone', 'valor_ponto', 'consentimento_lgpd']
                        
                        if not all(col in df_upload.columns for col in colunas_req):
                            st.error(f"O arquivo deve conter exatamente as colunas: {', '.join(colunas_req)}")
                        else:
                            sucessos = 0
                            erros = []
                            pb = st.progress(0)
                            tot = len(df_upload)
                            
                            for idx, row in df_upload.iterrows():
                                u_val = str(row['usuario']).strip()
                                s_val = str(row['senha']).strip()
                                n_val = str(row['nome']).strip()
                                bal_val = float(row['saldo']) if pd.notna(row['saldo']) else 0.0
                                t_val = str(row['tipo']).lower().strip()
                                tel_val = str(row['telefone']).strip()
                                vp_val = float(row['valor_ponto']) if pd.notna(row['valor_ponto']) else 0.50
                                lgpd_val = bool(row['consentimento_lgpd']) if pd.notna(row['consentimento_lgpd']) else False
                                
                                # Pula linhas totalmente vazias baseadas no usuário
                                if u_val.lower() == 'nan' or u_val == '':
                                    tot -= 1
                                    continue
                                
                                ok, msg = cadastrar_novo_usuario(u_val, s_val, n_val, bal_val, t_val, tel_val, vp_val, lgpd_val)
                                if ok:
                                    sucessos += 1
                                else:
                                    erros.append(f"Linha {idx+2} ({u_val}): {msg}")
                                    
                                if tot > 0: pb.progress((idx + 1) / tot)
                                
                            st.success(f"Lote processado! {sucessos} cadastros realizados com sucesso.")
                            if erros:
                                with st.expander("⚠️ Ver erros de importação"):
                                    for erro in erros: st.write(erro)
                            st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Erro ao ler o arquivo Excel. Verifique se o formato está correto: {e}")
                    
        with st.expander("💰 Distribuir Pontos (Soma no Ranking)", expanded=False):
            c_d1, c_d2, c_d3 = st.columns([2, 1, 1])
            df_users_list_dist = run_query("SELECT usuario FROM usuarios WHERE tipo NOT IN ('admin', 'staff', 'supervisor') ORDER BY usuario")
            lista_users = df_users_list_dist['usuario'].tolist() if not df_users_list_dist.empty else []
            target_users = c_d1.multiselect("Selecione os Usuários", ["Todos"] + lista_users)
            qtd_pontos = c_d2.number_input("Pontos", step=50, value=0)
            if c_d3.button("➕ Creditar", type="primary", use_container_width=True):
                if qtd_pontos > 0 and target_users:
                    if distribuir_pontos_multiplos(target_users, qtd_pontos): st.cache_data.clear(); modal_sucesso_salvamento(f"Crédito de {qtd_pontos}pts para {len(target_users)} usuários."); 
                else: st.warning("Selecione alguém e um valor maior que 0.")
                
        st.divider(); df_u = run_query("SELECT * FROM usuarios ORDER BY id") 
        if not df_u.empty:
            if "acesso_bolao" in df_u.columns: df_u = df_u.drop(columns=["acesso_bolao"])
            if "Notificar" not in df_u.columns: df_u.insert(0, "Notificar", False)
            edit_u = st.data_editor(df_u, use_container_width=True, key="ed_u", column_config={"Notificar": st.column_config.CheckboxColumn("Avisar?", default=False), "saldo": st.column_config.NumberColumn("Saldo (Gastar)", help="Dinheiro na carteira agora"), "pontos_historico": st.column_config.NumberColumn("Ranking (Total)", help="Total acumulado na vida (não zera)"), "tipo": st.column_config.SelectboxColumn("Tipo de Conta", options=["comum", "admin", "staff", "supervisor"], required=True), "valor_ponto": st.column_config.NumberColumn("Valor Ponto (R$)", format="%.2f"), "consentimento_lgpd": st.column_config.CheckboxColumn("LGPD?", disabled=True)})
            
            st.markdown("<br>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
            with c2:
                if st.button("💾 Salvar Tabela", use_container_width=True, key="btn_save_users"):
                    st.cache_data.clear()
                    try:
                        with conn.session as s:
                            for i, row in edit_u.iterrows():
                                v_ponto_salvar = float(row.get('valor_ponto', 0.50) or 0.50)
                                s.execute(text("UPDATE usuarios SET saldo=:s, pontos_historico=:ph, telefone=:t, nome=:n, tipo=:tp, valor_ponto=:vp WHERE id=:id"), {"s": float(row['saldo']), "ph": float(row['pontos_historico']), "t": str(row['telefone']), "n": str(row['nome']), "tp": str(row['tipo']), "vp": v_ponto_salvar, "id": int(row['id'])})
                            s.commit()
                        registrar_log("Admin", "Editou usuários na tabela"); modal_sucesso_salvamento(f"Tabela Usuários salva. {len(edit_u)} registros.")
                    except Exception as e: st.error(f"Erro ao salvar: {e}")
            with c3:
                if st.button("📤 Enviar Avisos", type="primary", use_container_width=True):
                    sel = edit_u[edit_u['Notificar'] == True]
                    if sel.empty: st.warning("Ninguém selecionado.")
                    else: processar_envios_dialog(sel, "usuarios")
                    
    with t3:
        with st.expander("⚙️ Reprecificação em Massa (Valor do Ponto)"):
            st.info("ℹ️ Utilize esta ferramenta para ajustar o preço de **TODOS** os produtos de uma só vez com base no valor do ponto em Reais.")
            c_base1, c_base2 = st.columns(2)
            valor_ponto_atual = c_base1.number_input("Valor ATUAL do Ponto (R$)", value=0.50, step=0.01, min_value=0.01, format="%.2f")
            valor_ponto_novo = c_base2.number_input("NOVO Valor do Ponto (R$)", value=0.50, step=0.01, min_value=0.01, format="%.2f")
            if valor_ponto_atual != valor_ponto_novo:
                st.write("---"); st.markdown("### 🔎 Simulação de Novos Preços"); fator = valor_ponto_atual / valor_ponto_novo
                df_preview = run_query("SELECT id, item, custo FROM premios")
                if not df_preview.empty:
                    df_preview['custo_novo'] = (df_preview['custo'] * fator).astype(int); df_preview['diferenca'] = df_preview['custo_novo'] - df_preview['custo']
                    st.dataframe(df_preview[['item', 'custo', 'custo_novo', 'diferenca']], use_container_width=True, hide_index=True)
                    st.warning(f"⚠️ **Atenção:** Esta ação irá alterar o preço de **{len(df_preview)} produtos**.")
                    if st.button("✅ CONFIRMAR REPRECIFICAÇÃO", type="primary"):
                        try:
                            with conn.session as sess:
                                for i, row in df_preview.iterrows():
                                    sess.execute(text("UPDATE premios SET custo = :c WHERE id = :id"), {"c": int(row['custo_novo']), "id": int(row['id'])})
                                sess.commit()
                            st.cache_data.clear(); modal_sucesso_salvamento(f"Reprecificação em massa executada. Fator: {fator:.2f}")
                        except Exception as e: st.error(f"Erro ao atualizar: {e}")
                        
        st.divider(); df_p = run_query("SELECT * FROM premios ORDER BY id")
        edit_p = st.data_editor(df_p, use_container_width=True, num_rows="dynamic", key="ed_p", column_config={"descricao": st.column_config.TextColumn("Descrição (Detalhes)", width="large")})
        if st.button("Salvar Prêmios"):
            st.cache_data.clear()
            try:
                with conn.session as sess:
                    for i, row in edit_p.iterrows():
                        if pd.notna(row['id']): 
                            sess.execute(text("UPDATE premios SET item=:i, imagem=:im, custo=:c, descricao=:d WHERE id=:id"), {"i": str(row['item']), "im": str(row['imagem']), "c": float(row['custo']), "d": str(row.get('descricao', '')), "id": int(row['id'])})
                        else:
                            if row['item']: sess.execute(text("INSERT INTO premios (item, imagem, custo, descricao) VALUES (:i, :im, :c, :d)"), {"i": str(row['item']), "im": str(row['imagem']), "c": float(row['custo']), "d": str(row.get('descricao', ''))})
                    sess.commit()
                modal_sucesso_salvamento(f"Catálogo de Prêmios salvo. {len(edit_p)} itens.")
            except Exception as e: st.error(f"Erro ao salvar prêmios: {e}")
            
    with t4: st.dataframe(run_query("SELECT * FROM logs ORDER BY id DESC LIMIT 50"), use_container_width=True)
    
    with t5:
        st.markdown("### 🎟️ Gestão de Sorteios/Rifas"); rifa_ativa = run_query("SELECT * FROM rifas WHERE status = 'ativa'")
        if not rifa_ativa.empty:
            r = rifa_ativa.iloc[0]; st.success(f"🔥 Sorteio Ativo: **{r['item_nome']}** (Custo: {r['custo_ticket']} pts)")
            qtd_tickets = run_query("SELECT COUNT(*) as qtd FROM rifa_tickets WHERE rifa_id = :rid", {"rid": int(r['id'])}, ttl=0)
            total = qtd_tickets.iloc[0]['qtd']; st.metric("Tickets Vendidos", total); st.divider()
            if st.button("🎲 SORTEAR VENCEDOR", type="primary"):
                if total == 0: st.error("Ninguém comprou ticket ainda!")
                else:
                    tickets = run_query("SELECT usuario FROM rifa_tickets WHERE rifa_id = :rid", {"rid": int(r['id'])}, ttl=0)
                    vencedor = random.choice(tickets['usuario'].tolist())
                    
                    user_data = run_query("SELECT * FROM usuarios WHERE LOWER(usuario) = LOWER(:u)", {"u": vencedor})
                    
                    if user_data.empty:
                        st.error(f"⚠️ Erro: O usuário sorteado '{vencedor}' não foi encontrado no cadastro.")
                    else:
                        nome_real = user_data.iloc[0]['nome']
                        telefone = str(user_data.iloc[0]['telefone'])
                        
                        with conn.session as s:
                            s.execute(text("DELETE FROM rifa_tickets WHERE rifa_id = :rid"), {"rid": int(r['id'])})
                            s.execute(text("INSERT INTO vendas (data, usuario, item, valor, status, email, nome_real, telefone) VALUES (NOW(), :u, :item, 0, 'Sorteio', '', :n, :t)"), {"u": vencedor, "item": f"GANHADOR RIFA: {r['item_nome']}", "n": nome_real, "t": telefone})
                            s.execute(text("UPDATE rifas SET status = 'encerrada', ganhador_usuario = :u WHERE id = :id"), {"u": vencedor, "id": int(r['id'])})
                            s.commit()
                            
                        img_premio = ""
                        df_p_img = run_query("SELECT imagem FROM premios WHERE id = :pid", {"pid": int(r['premio_id'])})
                        if not df_p_img.empty: img_premio = df_p_img.iloc[0]['imagem']
                        
                        st.cache_data.clear()
                        mostrar_vencedor_dialog(nome_real, vencedor, r['item_nome'], img_premio)
                        registrar_log("Sorteio", f"Vencedor: {vencedor} - Item: {r['item_nome']}")
                        time.sleep(5)
                        st.rerun()
                        
            if st.button("Cancelar Sorteio (Sem Vencedor)"):
                with conn.session as s:
                    s.execute(text("DELETE FROM rifa_tickets WHERE rifa_id = :rid"), {"rid": int(r['id'])})
                    s.execute(text("UPDATE rifas SET status = 'cancelada' WHERE id = :id"), {"id": int(r['id'])})
                    s.commit()
                st.warning("Cancelado e tickets limpos.")
                st.cache_data.clear()
                st.rerun()
        else:
            st.info("Nenhum sorteio ativo no momento. Configure um abaixo:")
            df_premios = run_query("SELECT id, item FROM premios")
            opcoes = {f"{row['id']} - {row['item']}": row['id'] for i, row in df_premios.iterrows()}
            escolha = st.selectbox("Escolha o Prêmio para Sortear:", list(opcoes.keys())) if opcoes else None
            custo_rifa = st.number_input("Custo do Ticket (Pontos)", min_value=1, value=50)
            if st.button("🚀 INICIAR SORTEIO", type="primary") and escolha:
                premio_id = opcoes[escolha]; nome_premio = escolha.split(" - ", 1)[1]
                run_transaction("INSERT INTO rifas (premio_id, item_nome, custo_ticket, status) VALUES (:pid, :nome, :custo, 'ativa')", {"pid": premio_id, "nome": nome_premio, "custo": custo_rifa})
                st.cache_data.clear()
                st.success("Sorteio Criado!"); st.rerun()

def tela_supervisor():
    st.subheader("📦 Visão Geral de Todos os Resgates")
    df_v = run_query("SELECT id, data, usuario, nome_real, item, valor, status, telefone, email, codigo_vale, recebido_user FROM vendas ORDER BY id DESC")
    
    if not df_v.empty:
        c_filtro1, c_filtro2 = st.columns(2)
        status_unicos = df_v['status'].unique().tolist()
        filtro_status = c_filtro1.multiselect("Filtrar por Status", status_unicos)
        busca_user = c_filtro2.text_input("Buscar Usuário (Nome ou Login)")

        if filtro_status:
            df_v = df_v[df_v['status'].isin(filtro_status)]
        if busca_user:
            df_v = df_v[df_v['usuario'].str.contains(busca_user, case=False, na=False) | df_v['nome_real'].str.contains(busca_user, case=False, na=False)]

        st.metric("Total de Pedidos Encontrados", len(df_v))
        
        st.dataframe(
            df_v,
            use_container_width=True,
            hide_index=True,
            column_config={
                "data": st.column_config.DatetimeColumn("Data", format="DD/MM/YYYY HH:mm"),
                "valor": st.column_config.NumberColumn("Valor (pts)"),
                "recebido_user": st.column_config.CheckboxColumn("User Recebeu?")
            }
        )
    else:
        st.info("Nenhum registro de venda encontrado.")

def tela_principal():
    u_cod, u_nome, sld, tipo = st.session_state.usuario_cod, st.session_state.usuario_nome, st.session_state.saldo_atual, st.session_state.tipo_usuario
    valor_ponto_usuario = st.session_state.get('valor_ponto_usuario', 0.50); valor_padrao_ponto = 0.50 

    # --- VERIFICAÇÃO DE LGPD ---
    if st.session_state.get('lgpd_pendente', False):
        modal_consentimento_lgpd()
    
    # Se já aceitou, segue o fluxo normal
    else:
        # MENU SUPERIOR E ADM CONTROLS - LAYOUT ORIGINAL RESTAURADO
        if tipo == 'admin':
            cols = st.columns([3, 1.5], gap="medium")
            c_banner = cols[0]
            with cols[1]:
                c_btn_top = st.columns(2, gap="small")
                c_btn_bot = st.columns(2, gap="small")
                with c_btn_top[0]:
                    if st.button("Atualizar", type="secondary", use_container_width=True): st.cache_data.clear(); st.toast("Sincronizado!", icon="✅"); time.sleep(1); st.rerun()
                with c_btn_top[1]:
                    if st.button("Perfil", type="secondary", use_container_width=True): abrir_modal_perfil(u_cod)
                with c_btn_bot[0]:
                    label = "Ver Loja" if st.session_state.admin_mode else "Voltar"
                    if st.button(label, type="secondary", use_container_width=True): st.session_state.admin_mode = not st.session_state.admin_mode; st.rerun()
                with c_btn_bot[1]:
                    if st.button("Sair", type="secondary", use_container_width=True): realizar_logout()
        
        elif tipo == 'supervisor':
            cols = st.columns([3, 1.5], gap="medium")
            c_banner = cols[0]
            with cols[1]:
                c_btn_top = st.columns(2, gap="small")
                c_btn_bot = st.columns(1, gap="small")
                with c_btn_top[0]:
                     if st.button("Perfil", type="secondary", use_container_width=True): abrir_modal_perfil(u_cod)
                with c_btn_top[1]:
                    if st.button("Sair", type="secondary", use_container_width=True): realizar_logout()
                with c_btn_bot[0]:
                    label_sup = "Ver Loja" if st.session_state.supervisor_mode else "Painel Supervisor"
                    if st.button(label_sup, type="primary", use_container_width=True): 
                        st.session_state.supervisor_mode = not st.session_state.supervisor_mode
                        st.rerun()

        else:
            cols = st.columns([3, 1], gap="small")
            c_banner = cols[0]
            c_buttons = cols[1]
            with c_buttons:
                if st.button("👤 Meu Perfil", type="secondary", use_container_width=True): abrir_modal_perfil(u_cod)
                if st.button("❌ Sair", type="secondary", use_container_width=True): realizar_logout()
        
        with c_banner:
            titulo_painel = "Painel Supervisor 👁️" if (tipo == 'supervisor' and st.session_state.supervisor_mode) else f"Olá, {u_nome}! 👋"
            subtitulo = "Acompanhamento total de resgates." if (tipo == 'supervisor' and st.session_state.supervisor_mode) else "Agora você pode trocar seus pontos por prêmios incríveis!"
            st.markdown(f'''<div class="header-style"><div style="display:flex; justify-content:space-between; align-items:center;"><div><h2 style="margin:0; color:white;">{titulo_painel}</h2><p style="margin:0; opacity:0.9; color:white;">{subtitulo}</p></div><div style="text-align:right; color:white;"><span class="saldo-label">SEU SALDO</span><br><span class="saldo-valor">{sld:,.0f}</span> pts</div></div></div>''', unsafe_allow_html=True)
        
        st.divider()
        
        if tipo == 'admin' and st.session_state.admin_mode: 
            tela_admin()
        elif tipo == 'supervisor' and st.session_state.supervisor_mode: 
            tela_supervisor()
        else:
            abas_nome = ["🎁 Catálogo", "🍀 Sorteio", "📜 Meus Resgates", "🏆 Ranking"]
            abas = st.tabs(abas_nome)
            
            with abas[abas_nome.index("🎁 Catálogo")]:
                busca = st.text_input("🔍 Buscar Produtos", placeholder="Digite o nome do prêmio...")
                df_p = run_query("SELECT * FROM premios ORDER BY id")
                if not df_p.empty:
                    if busca: df_p = df_p[df_p['item'].str.contains(busca, case=False, na=False)]
                    if df_p.empty: st.warning("Nenhum produto encontrado.")
                    else:
                        cols_cat = st.columns(4)
                        for i, (_, row) in enumerate(df_p.iterrows()):
                            with cols_cat[i % 4]:
                                with st.container(border=True):
                                    if row['imagem']: st.image(processar_link_imagem(row['imagem']))
                                    cst = int(row['custo'] * (valor_padrao_ponto / valor_ponto_usuario))
                                    st.markdown(f"**{row['item']}**\n<br><div style='color:#0066cc; font-weight:bold;'>{cst} pts</div>", unsafe_allow_html=True)
                                    c_det, c_res = st.columns(2)
                                    with c_det: 
                                        if st.button("Detalhes", key=f"det_{row['id']}", use_container_width=True): ver_detalhes_produto(row['item'], row['imagem'], cst, row.get('descricao', ''))
                                    with c_res: 
                                        if sld >= cst and st.button("RESGATAR", key=f"b_{row['id']}", type="primary", use_container_width=True): confirmar_resgate_dialog(row['item'], cst, u_cod)
                else: st.info("Catálogo vazio.")
            
            with abas[abas_nome.index("🍀 Sorteio")]:
                rifa_ativa = run_query("SELECT * FROM rifas WHERE status = 'ativa'")
                if not rifa_ativa.empty:
                    r = rifa_ativa.iloc[0]; img_premio = ""
                    df_p_img = run_query("SELECT imagem FROM premios WHERE id = :pid", {"pid": int(r['premio_id'])})
                    if not df_p_img.empty: img_premio = df_p_img.iloc[0]['imagem']
                    st.markdown(f"<div class='rifa-card'><div class='rifa-tag'>🍀 SORTEIO ATIVO</div><h3>{r['item_nome']}</h3></div>", unsafe_allow_html=True)
                    if img_premio: st.image(processar_link_imagem(img_premio), width=200)
                    if st.button(f"🎟️ COMPRAR TICKET ({r['custo_ticket']} pts)", type="primary"): confirmar_compra_ticket(int(r['id']), r['custo_ticket'], u_cod)
                else: st.info("Nenhum sorteio ativo no momento.")
                
            with abas[abas_nome.index("📜 Meus Resgates")]:
                st.info("### 📜 Acompanhamento\nPedido recebido! Prazo: **5 dias úteis** no seu Whatsapp informado no momento do resgate!.")
                meus_pedidos = run_query("SELECT id, data, item, valor, status, codigo_vale, recebido_user FROM vendas WHERE LOWER(usuario) = LOWER(:u) ORDER BY data DESC", {"u": u_cod})
                if not meus_pedidos.empty:
                    editor_pedidos = st.data_editor(meus_pedidos, use_container_width=True, hide_index=True, key="editor_meus_pedidos", column_config={"id": st.column_config.TextColumn("ID", disabled=True), "data": st.column_config.DatetimeColumn("Data", disabled=True, format="DD/MM/YYYY"), "item": st.column_config.TextColumn("Item", disabled=True), "valor": st.column_config.NumberColumn("Valor", disabled=True), "status": st.column_config.TextColumn("Status", disabled=True), "codigo_vale": st.column_config.TextColumn("Código/Vale", disabled=True), "recebido_user": st.column_config.CheckboxColumn("Já Recebeu?", help="Marque se você já recebeu seu prêmio")}, disabled=["id", "data", "item", "valor", "status", "codigo_vale"])
                    if st.button("💾 Confirmar Recebimento"):
                        with conn.session as s:
                            for i, row in editor_pedidos.iterrows():
                                if row['recebido_user']: s.execute(text("UPDATE vendas SET recebido_user = TRUE WHERE id = :id"), {"id": row['id']})
                                else: s.execute(text("UPDATE vendas SET recebido_user = FALSE WHERE id = :id"), {"id": row['id']})
                            s.commit()
                        st.cache_data.clear() 
                        st.toast("Status de recebimento atualizado!", icon="✅"); time.sleep(1); st.rerun()
                else: st.write("Nenhum pedido encontrado.")
            
            with abas[abas_nome.index("🏆 Ranking")]:
                st.markdown("### 🏆 Top Users (Histórico)")
                st.caption("Este ranking considera todos os pontos já ganhos, independente se já foram gastos ou zerados.")
                df_rank = run_query("SELECT usuario, pontos_historico FROM usuarios WHERE tipo NOT IN ('admin', 'staff', 'supervisor') ORDER BY pontos_historico DESC LIMIT 10")
                if not df_rank.empty:
                    df_rank['pontos_historico'] = df_rank['pontos_historico'].fillna(0).astype(int)
                    df_rank = df_rank.rename(columns={"usuario": "Usuário", "pontos_historico": "Pontos Acumulados"})
                    st.dataframe(df_rank, use_container_width=True, hide_index=True)
                else: st.info("Ranking ainda vazio.")

if __name__ == "__main__":
    if "rt" in st.query_params: tela_nova_senha_token(st.query_params["rt"])
    else: verificar_sessao_automatica(); tela_principal() if st.session_state.get('logado', False) else tela_login()