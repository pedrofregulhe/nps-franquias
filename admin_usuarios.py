"""
Painel administrativo de usuarios do Painel NPS.

Visivel para os perfis 'admin' e 'operacao'. Cobre:
  - cadastro/edicao de usuarios e telefones (o telefone e obrigatorio para o 2FA);
  - vinculo usuario -> franquias (o recorte usa correspondencia exata do nome);
  - importacao da planilha "Usuarios qualtrics - Franquias.xlsx";
  - reset de senha com envio por WhatsApp;
  - auditoria (nps_logs).

O perfil 'operacao' recebe somente_leitura=True: consulta cadastros, diagnostico
e auditoria, mas nao altera nada -- as abas de criacao e importacao nem aparecem
e os campos de edicao vem desabilitados.
"""

import streamlit as st
import pandas as pd
import os

from auth import (
    conn, run_query, run_transaction, registrar_log,
    gerar_hash, gerar_senha_aleatoria, formatar_telefone,
    enviar_sms, enviar_codigo_2fa, varrer_variantes_whatsapp, limpar_cache_banco,
    TIPOS_ACESSO, TIPOS_IRRESTRITOS, ROTULO_TIPO,
)
from sqlalchemy import text

PLANILHA_USUARIOS = "Usuários qualtrics - Franquias.xlsx"


# ==========================================================================
# LEITURA DA PLANILHA DE USUARIOS
# ==========================================================================
def ler_planilha_usuarios(caminho=PLANILHA_USUARIOS):
    """
    Consolida a planilha em um registro por usuario.

    A planilha traz uma linha por bloco de franquias, entao o mesmo usuario
    pode aparecer varias vezes (ex.: Jaime Ventura em 3 blocos). As franquias
    de todas as linhas do usuario sao unidas.
    """
    if not os.path.exists(caminho):
        return None, f"Arquivo '{caminho}' nao encontrado."
    try:
        df = pd.read_excel(caminho)
    except Exception as e:
        return None, f"Erro ao ler a planilha: {e}"

    obrigatorias = {'Nome', 'User'}
    if not obrigatorias.issubset(df.columns):
        return None, f"A planilha precisa das colunas {obrigatorias}."

    cols_franquia = [c for c in df.columns if str(c).strip().lower().startswith('franquia')]

    registros = {}
    for _, linha in df.iterrows():
        login = str(linha['User']).strip()
        if not login or login.lower() == 'nan':
            continue
        if login not in registros:
            registros[login] = {
                'usuario': login,
                'nome': str(linha.get('Nome', '')).strip(),
                'email': str(linha.get('E-mail', '') or '').strip(),
                'perfil': str(linha.get('Perfil', '') or '').strip(),
                'franquias': set(),
            }
        for col in cols_franquia:
            valor = linha.get(col)
            if pd.notna(valor):
                nome_fr = str(valor).strip()
                if nome_fr and nome_fr.lower() != 'nan':
                    registros[login]['franquias'].add(nome_fr)

    for reg in registros.values():
        reg['franquias'] = sorted(reg['franquias'])
    return list(registros.values()), None


# ==========================================================================
# OPERACOES DE BANCO
# ==========================================================================
def listar_usuarios():
    return run_query("""
        SELECT u.id, u.usuario, u.nome, u.email, u.perfil, u.tipo, u.telefone,
               u.ativo, u.ultimo_acesso,
               COUNT(f.id) AS qtd_franquias
        FROM nps_usuarios u
        LEFT JOIN nps_usuario_franquias f ON f.usuario_id = u.id
        GROUP BY u.id
        ORDER BY u.tipo DESC, u.nome
    """, ttl=0)


def salvar_franquias(usuario_id, franquias):
    """Substitui o vinculo de franquias do usuario."""
    with conn.session as s:
        s.execute(text("DELETE FROM nps_usuario_franquias WHERE usuario_id = :uid"),
                  {"uid": int(usuario_id)})
        for fr in sorted(set(str(f).strip() for f in franquias if str(f).strip())):
            s.execute(
                text("INSERT INTO nps_usuario_franquias (usuario_id, franquia) VALUES (:uid, :fr) "
                     "ON CONFLICT (usuario_id, franquia) DO NOTHING"),
                {"uid": int(usuario_id), "fr": fr}
            )
        s.commit()


def criar_usuario(usuario, nome, senha, tipo, telefone="", email="", perfil="", franquias=None):
    usuario = str(usuario).strip()
    if not usuario or not nome or not senha:
        return False, "Usuario, nome e senha sao obrigatorios."
    existente = run_query("SELECT id FROM nps_usuarios WHERE LOWER(usuario) = LOWER(:u)",
                          {"u": usuario}, ttl=0)
    if not existente.empty:
        return False, f"O usuario '{usuario}' ja existe."
    try:
        with conn.session as s:
            resultado = s.execute(
                text("""INSERT INTO nps_usuarios (usuario, senha, nome, email, perfil, tipo, telefone)
                        VALUES (:u, :s, :n, :e, :p, :t, :tel) RETURNING id"""),
                {"u": usuario, "s": gerar_hash(senha), "n": nome, "e": email,
                 "p": perfil, "t": tipo, "tel": formatar_telefone(telefone) if telefone else None}
            )
            novo_id = resultado.scalar()
            s.commit()
        if franquias:
            salvar_franquias(novo_id, franquias)
        registrar_log("Novo usuario", f"Criou '{usuario}' (tipo={tipo}, franquias={len(franquias or [])})")
        return True, f"Usuario '{usuario}' criado."
    except Exception as e:
        return False, f"Erro ao criar: {e}"


def franquias_do_usuario(usuario_id):
    """Franquias vinculadas, ja unificadas (sem grade, nomenclatura atual)."""
    from franquias import unificar_lista
    df = run_query("SELECT franquia FROM nps_usuario_franquias WHERE usuario_id = :uid ORDER BY franquia",
                   {"uid": int(usuario_id)}, ttl=0)
    return [] if df.empty else unificar_lista(df['franquia'].tolist())


# ==========================================================================
# INTERFACE
# ==========================================================================
def render_admin_usuarios(franquias_base, somente_leitura=False):
    """
    franquias_base: todas as franquias presentes nos arquivos xlsx do NPS.
                    Usada para validar os vinculos (o recorte e por nome exato).
    somente_leitura: perfil 'operacao'. Consulta tudo, mas nao altera cadastro
                    nenhum -- as abas de criacao/importacao somem e os campos
                    de edicao ficam desabilitados.
    """
    if somente_leitura:
        st.subheader("Usuários (consulta)")
        st.info(
            "Seu perfil é **Operação**: você acompanha os cadastros e a auditoria, "
            "mas alterações são exclusivas do administrador."
        )
        aba_lista, aba_diag, aba_logs = st.tabs(
            ["Usuários", "Diagnóstico de envio", "Auditoria"]
        )
        aba_novo = aba_import = None
    else:
        st.subheader("Administração de usuários")
        aba_lista, aba_novo, aba_import, aba_diag, aba_logs = st.tabs(
            ["Usuários", "Novo usuário", "Importar planilha", "Diagnóstico de envio", "Auditoria"]
        )

    # ---------------------------------------------------------------- LISTA
    with aba_lista:
        c_atualiza, c_vazio = st.columns([1, 3])
        with c_atualiza:
            if st.button("🔄 Atualizar do banco", use_container_width=True, key="btn_refresh_users"):
                limpar_cache_banco()
                st.toast("Dados recarregados do Neon.", icon="✅")
                st.rerun()

        df_users = listar_usuarios()
        if df_users.empty:
            st.info("Nenhum usuário cadastrado. Use a aba 'Importar planilha' para carregar a base inicial.")
        else:
            sem_telefone = df_users[df_users['telefone'].isna() | (df_users['telefone'].astype(str).str.len() < 12)]
            if not sem_telefone.empty:
                st.warning(
                    f"{len(sem_telefone)} usuário(s) sem telefone válido. "
                    "Eles não conseguem fazer login porque o código 2FA é enviado por WhatsApp."
                )

            st.dataframe(
                df_users.rename(columns={
                    'usuario': 'Usuário', 'nome': 'Nome', 'email': 'E-mail', 'perfil': 'Perfil',
                    'tipo': 'Tipo', 'telefone': 'Telefone', 'ativo': 'Ativo',
                    'ultimo_acesso': 'Último acesso', 'qtd_franquias': 'Franquias'
                }).drop(columns=['id']),
                use_container_width=True, hide_index=True
            )

            st.markdown("---")
            st.markdown("#### Editar usuário")
            opcoes = {f"{r['nome']} ({r['usuario']})": int(r['id']) for _, r in df_users.iterrows()}
            escolhido = st.selectbox("Selecione:", list(opcoes.keys()), key="ed_seletor")
            uid = opcoes[escolhido]
            atual = df_users[df_users['id'] == uid].iloc[0]

            # As chaves dos campos incluem o uid de proposito. Com chave fixa,
            # o Streamlit preserva o valor digitado entre reruns e ignora o
            # 'value' novo -- ao trocar de usuario a tela continuava mostrando
            # os dados do anterior.
            k = f"_{uid}"

            trava = somente_leitura  # desabilita todos os campos de edicao

            c1, c2 = st.columns(2)
            with c1:
                novo_nome = st.text_input("Nome", value=str(atual['nome'] or ''),
                                          key=f"ed_nome{k}", disabled=trava)
                novo_email = st.text_input("E-mail", value=str(atual['email'] or ''),
                                           key=f"ed_email{k}", disabled=trava)
                novo_tel = st.text_input(
                    "Telefone (celular com DDD)", value=str(atual['telefone'] or ''),
                    help="Obrigatório para o 2FA. Ex.: 11987654321",
                    key=f"ed_tel{k}", disabled=trava
                )
            with c2:
                tipo_atual = str(atual['tipo'] or 'comum').lower().strip()
                novo_tipo = st.selectbox(
                    "Tipo de acesso", TIPOS_ACESSO,
                    index=TIPOS_ACESSO.index(tipo_atual) if tipo_atual in TIPOS_ACESSO else 0,
                    help="admin: vê tudo e administra usuários | operacao: vê tudo, "
                         "sem editar cadastros | comum: só as franquias vinculadas.",
                    key=f"ed_tipo{k}", disabled=trava
                )
                novo_perfil = st.text_input("Perfil (informativo)", value=str(atual['perfil'] or ''),
                                            key=f"ed_perfil{k}", disabled=trava)
                novo_ativo = st.checkbox("Acesso ativo", value=bool(atual['ativo']),
                                         key=f"ed_ativo{k}", disabled=trava)

            vinculadas = franquias_do_usuario(uid)
            if novo_tipo in TIPOS_IRRESTRITOS:
                st.info(
                    f"Usuário **{ROTULO_TIPO.get(novo_tipo, novo_tipo)}**: enxerga todas as "
                    "franquias, sem necessidade de vínculo."
                )
                novas_franquias = vinculadas
            else:
                orfas = [f for f in vinculadas if f not in franquias_base]
                opcoes_fr = sorted(set(franquias_base) | set(vinculadas))
                novas_franquias = st.multiselect(
                    "Franquias visíveis para este usuário",
                    options=opcoes_fr, default=vinculadas,
                    key=f"ed_franquias{k}", disabled=trava
                )
                if orfas:
                    st.warning(
                        f"{len(orfas)} franquia(s) vinculada(s) não existem na base de NPS atual e não "
                        f"retornarão dados: {', '.join(orfas[:5])}" + (" ..." if len(orfas) > 5 else "")
                    )

            if somente_leitura:
                st.caption("Modo consulta: para alterar qualquer campo acima, procure um administrador.")
            else:
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("Salvar alterações", type="primary", use_container_width=True):
                        tel_fmt = formatar_telefone(novo_tel) if novo_tel.strip() else None
                        if tel_fmt and len(tel_fmt) < 12:
                            st.error("Telefone inválido. Informe DDD + número.")
                        else:
                            run_transaction("""
                                UPDATE nps_usuarios
                                   SET nome = :n, email = :e, telefone = :tel,
                                       tipo = :t, perfil = :p, ativo = :a
                                 WHERE id = :id
                            """, {"n": novo_nome, "e": novo_email, "tel": tel_fmt, "t": novo_tipo,
                                  "p": novo_perfil, "a": novo_ativo, "id": uid})
                            if novo_tipo not in TIPOS_IRRESTRITOS:
                                salvar_franquias(uid, novas_franquias)
                            registrar_log("Usuario atualizado", f"id={uid} usuario={atual['usuario']}")
                            st.success("Alterações salvas.")
                            st.rerun()

                with b2:
                    if st.button("Resetar senha e enviar", use_container_width=True):
                        tel = str(atual['telefone'] or '')
                        if len(formatar_telefone(tel)) < 12:
                            st.error("Cadastre um telefone válido antes de resetar a senha.")
                        else:
                            nova = gerar_senha_aleatoria()
                            run_transaction("UPDATE nps_usuarios SET senha = :s WHERE id = :id",
                                            {"s": gerar_hash(nova), "id": uid})
                            registrar_log("Reset de senha", f"Usuario: {atual['usuario']}")
                            ok, canal, det = enviar_codigo_2fa(tel, nova)
                            if ok:
                                st.success(f"Senha redefinida e enviada por {canal}.")
                            else:
                                st.warning(
                                    f"Senha redefinida, mas o envio falhou. Passe a senha ao usuário "
                                    f"por outro meio: **{nova}**"
                                )
                                st.caption(f"Detalhe técnico: {det}")

                with b3:
                    if st.button("Excluir usuário", use_container_width=True):
                        if uid == st.session_state.get('usuario_id'):
                            st.error("Você não pode excluir o próprio acesso.")
                        else:
                            run_transaction("DELETE FROM nps_usuarios WHERE id = :id", {"id": uid})
                            registrar_log("Usuario excluido", f"usuario={atual['usuario']}")
                            st.success("Usuário excluído.")
                            st.rerun()

    # Criacao e importacao alteram cadastro: escondidas do perfil operacao.
    if not somente_leitura:
        # ----------------------------------------------------------- NOVO USUARIO
        with aba_novo:
            with st.form("form_novo_usuario"):
                c1, c2 = st.columns(2)
                with c1:
                    n_usuario = st.text_input("Usuário (login)")
                    n_nome = st.text_input("Nome completo")
                    n_email = st.text_input("E-mail")
                with c2:
                    n_tel = st.text_input("Telefone (celular com DDD)", help="Obrigatório para o 2FA.")
                    n_tipo = st.selectbox(
                        "Tipo de acesso", TIPOS_ACESSO,
                        help="admin: vê tudo e administra usuários | operacao: vê tudo, "
                             "sem editar cadastros | comum: só as franquias vinculadas."
                    )
                    n_perfil = st.text_input("Perfil (informativo)", placeholder="Coordenador / Franqueado")

                n_franquias = st.multiselect(
                    "Franquias visíveis (somente para tipo 'comum')",
                    options=sorted(franquias_base)
                )
                n_senha = st.text_input("Senha inicial", type="password",
                                        help="Deixe em branco para gerar automaticamente e enviar por WhatsApp.")

                if st.form_submit_button("Cadastrar", type="primary", use_container_width=True):
                    senha_final = n_senha.strip() or gerar_senha_aleatoria()
                    ok, msg = criar_usuario(
                        n_usuario, n_nome, senha_final, n_tipo,
                        telefone=n_tel, email=n_email, perfil=n_perfil,
                        franquias=n_franquias if n_tipo == 'comum' else None
                    )
                    if ok:
                        st.success(msg)
                        if not n_senha.strip():
                            enviado, canal, det = enviar_codigo_2fa(n_tel, senha_final)
                            if enviado:
                                st.info(f"Senha provisoria enviada por {canal} para {n_usuario.strip()}.")
                            else:
                                st.warning(f"Envio falhou. Senha gerada: **{senha_final}**")
                                st.caption(f"Detalhe tecnico: {det}")
                    else:
                        st.error(msg)

        # -------------------------------------------------------------- IMPORTAR
        with aba_import:
            st.markdown(f"Importa os usuarios de **{PLANILHA_USUARIOS}** como acesso do tipo `comum`.")
            st.caption(
                "A planilha nao possui telefone. Os usuarios sao criados sem telefone e nao conseguem "
                "logar ate que voce cadastre o celular na aba 'Usuarios'."
            )

            registros, erro = ler_planilha_usuarios()
            if erro:
                st.error(erro)
            else:
                base_set = set(franquias_base)
                resumo = []
                for reg in registros:
                    casadas = [f for f in reg['franquias'] if f in base_set]
                    resumo.append({
                        'Usuario': reg['usuario'],
                        'Nome': reg['nome'],
                        'Perfil': reg['perfil'],
                        'Franquias na planilha': len(reg['franquias']),
                        'Encontradas na base NPS': len(casadas),
                        'Sem correspondencia': len(reg['franquias']) - len(casadas),
                    })
                df_resumo = pd.DataFrame(resumo)
                st.dataframe(df_resumo, use_container_width=True, hide_index=True)

                total_fr = int(df_resumo['Franquias na planilha'].sum())
                total_ok = int(df_resumo['Encontradas na base NPS'].sum())
                c1, c2, c3 = st.columns(3)
                c1.metric("Usuarios na planilha", len(registros))
                c2.metric("Vinculos de franquia", total_fr)
                c3.metric("Com correspondencia exata", total_ok)

                if total_ok < total_fr:
                    st.warning(
                        f"{total_fr - total_ok} vinculo(s) nao tem franquia correspondente na base de NPS. "
                        "Eles serao gravados mesmo assim, mas nao retornam dados enquanto o nome nao coincidir "
                        "exatamente com o da coluna 'Franquia' dos arquivos xlsx."
                    )

                sobrescrever = st.checkbox(
                    "Atualizar usuarios que ja existem (nome, e-mail, perfil e franquias)", value=True
                )
                st.warning("A importacao nao altera senhas nem telefones de usuarios ja cadastrados.")

                if st.button("Executar importacao", type="primary"):
                    criados, atualizados, ignorados = 0, 0, 0
                    for reg in registros:
                        existente = run_query(
                            "SELECT id FROM nps_usuarios WHERE LOWER(usuario) = LOWER(:u)",
                            {"u": reg['usuario']}, ttl=0
                        )
                        if existente.empty:
                            ok, _ = criar_usuario(
                                reg['usuario'], reg['nome'], gerar_senha_aleatoria(), 'comum',
                                telefone="", email=reg['email'], perfil=reg['perfil'],
                                franquias=reg['franquias']
                            )
                            criados += 1 if ok else 0
                        elif sobrescrever:
                            uid = int(existente.iloc[0]['id'])
                            run_transaction(
                                "UPDATE nps_usuarios SET nome = :n, email = :e, perfil = :p WHERE id = :id",
                                {"n": reg['nome'], "e": reg['email'], "p": reg['perfil'], "id": uid}
                            )
                            salvar_franquias(uid, reg['franquias'])
                            atualizados += 1
                        else:
                            ignorados += 1
                    registrar_log("Importacao de usuarios",
                                  f"criados={criados} atualizados={atualizados} ignorados={ignorados}")
                    st.success(f"Importacao concluida. Criados: {criados} | Atualizados: {atualizados} | Ignorados: {ignorados}")
                    st.info("Proximo passo: cadastre os telefones na aba 'Usuarios' para liberar o login.")

    # ----------------------------------------------------------- DIAGNOSTICO
    with aba_diag:
        st.markdown("#### Teste de entrega do codigo de verificacao")
        st.caption(
            "Dispara uma mensagem real para o numero informado e mostra a resposta crua da Infobip. "
            "Use para descobrir o idioma correto do template antes de liberar os franqueados."
        )

        cfg_template = st.secrets.get("TEMPLATE_2FA", "nps_acesso")
        cfg_idioma = st.secrets.get("TEMPLATE_2FA_IDIOMA", "pt_BR")
        c1, c2, c3 = st.columns(3)
        c1.metric("Template", cfg_template)
        c2.metric("Idioma configurado", cfg_idioma)
        c3.metric("Fallback SMS", "ligado" if st.secrets.get("FALLBACK_SMS", True) else "desligado")

        tel_teste = st.text_input("Telefone de teste (com DDD)", placeholder="11987654321")
        canal_teste = st.radio(
            "O que testar:",
            ["Fluxo real (WhatsApp com fallback para SMS)",
             "Somente WhatsApp - varrer idiomas",
             "Somente SMS"],
            key="diag_canal"
        )

        if st.button("Enviar teste", type="primary"):
            if len(formatar_telefone(tel_teste)) < 12:
                st.error("Informe um numero valido com DDD.")
            else:
                codigo = "123456"
                if canal_teste.startswith("Fluxo real"):
                    ok, canal, det = enviar_codigo_2fa(tel_teste, codigo)
                    (st.success if ok else st.error)(
                        f"{'Entregue via ' + canal if ok else 'Falhou'}"
                    )
                    st.code(det, language="text")

                elif canal_teste.startswith("Somente WhatsApp"):
                    st.write("Testando combinacoes de idioma e estrutura de botao...")
                    resultados, vencedora = varrer_variantes_whatsapp(
                        tel_teste, codigo, nome_template=cfg_template
                    )
                    st.dataframe(
                        pd.DataFrame(resultados).rename(columns={
                            'idioma': 'Idioma', 'botao': 'Botao',
                            'ok': 'Aceito', 'detalhe': 'Resposta da Infobip'}),
                        use_container_width=True, hide_index=True
                    )
                    if vencedora:
                        st.success(
                            f"Combinacao aceita: idioma **{vencedora['idioma']}**, "
                            f"botao **{vencedora['botao']}**"
                        )
                        st.markdown("Fixe no `secrets.toml` para o login usar sempre esta:")
                        st.code(
                            f'TEMPLATE_2FA_IDIOMA = "{vencedora["idioma"]}"\n'
                            f'TEMPLATE_2FA_BOTAO = "{vencedora["botao"]}"',
                            language="toml"
                        )
                    else:
                        st.error("Nenhuma combinacao foi aceita. Veja a coluna de resposta acima.")
                        st.markdown(
                            "Se a resposta repetir *template not found* ou *does not exist*, o problema "
                            f"nao e a estrutura: confira na Infobip se o remetente "
                            f"**{st.secrets.get('INFOBIP_SENDER','')}** e o dono do template "
                            f"`{cfg_template}` — um template aprovado em outro numero/conta WABA nao "
                            "pode ser disparado por este remetente."
                        )
                else:
                    ok, det = enviar_sms(tel_teste, f"Painel NPS - teste de envio: {codigo}")
                    (st.success if ok else st.error)("SMS aceito" if ok else "SMS falhou")
                    st.code(det, language="text")

                st.info(
                    "Aceito pela Infobip nao garante entrega. Se a resposta vier OK mas nada chegar "
                    "no aparelho, o bloqueio esta na operadora ou nas regras do WhatsApp Business."
                )

    # ---------------------------------------------------------------- LOGS
    with aba_logs:
        df_logs = run_query("SELECT data, responsavel, acao, detalhes FROM nps_logs ORDER BY id DESC LIMIT 300", ttl=0)
        if df_logs.empty:
            st.info("Nenhum registro de auditoria ainda.")
        else:
            st.dataframe(
                df_logs.rename(columns={'data': 'Data', 'responsavel': 'Responsavel',
                                        'acao': 'Acao', 'detalhes': 'Detalhes'}),
                use_container_width=True, hide_index=True
            )
