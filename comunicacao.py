"""
Aba "Comunicação Franquias" — envio dos indicadores de NPS por e-mail.

Visível apenas para administradores. Monta, para cada usuário comum, um e-mail
HTML com os indicadores do mês atual e a variação contra o mês anterior:
o consolidado das franquias dele, a quebra por franquia quando houver mais de
uma, os principais motivos de detratores/neutros e a nota 5Star.

DESEMPENHO
----------
O Streamlit renderiza o corpo de TODAS as abas a cada rerun — então tudo aqui
roda mesmo quando o admin está olhando outra aba. A primeira versão fazia, por
rerun, 31 consultas ao Neon (uma por usuário) e 31 varreduras da base inteira.
Qualquer clique no painel pagava esse preço.

Agora: uma consulta única traz todos os vínculos, e uma única passada de
groupby produz os contadores por franquia. Como os contadores são aditivos
(soma de promotores, detratores, respostas), o pacote de cada usuário vira
soma de dicionários — aritmética pura, sem tocar no DataFrame. O resultado
fica em cache, e a aba roda dentro de st.fragment para que interações locais
não reexecutem o painel inteiro.

ENVIO
-----
Outlook clássico via COM (pywin32), mesma técnica do projeto Massivo: aproveita
a sessão logada, sem SMTP e sem depender da TI. Remetente exibido:
cx.assinatura@culligan.com. Só funciona local, no Windows, com o Outlook aberto —
no Streamlit Cloud a aba detecta o ambiente e explica, em vez de falhar no meio.

HTML
----
O Outlook desktop renderiza com o motor do Word: nada de flexbox, grid ou
gradiente. Tudo em tabelas com estilo inline, 600px. Os gráficos são barras
feitas de células de tabela — imagem em base64 é bloqueada pelo Outlook, e
hospedar uma imagem por destinatário não se sustenta.
"""

import streamlit as st
import pandas as pd
import time
from collections import Counter

# --- Identidade do remetente (mesma do projeto Massivo) ---
EMAIL_CONTA = "ext-potavio@culligan.com"      # conta que efetivamente envia
EMAIL_DE = "cx.assinatura@culligan.com"       # remetente exibido
BANNER_URL = ("https://raichu-uploads.s3.amazonaws.com/"
              "companypageconfiguration_71281100-b5e8-464b-bf51-5182fb325307.jpg")

# O Microsoft 365 limita a ~30 mensagens/minuto. 2s entre envios fica abaixo
# disso e evita erro de COM ocupado.
PAUSA_ENTRE_ENVIOS_S = 2

# Quantos motivos de detratores/neutros entram no e-mail.
TOP_MOTIVOS = 5

AZUL = "#005b9f"
VERDE = "#0E9F6E"
AMBAR = "#D9A407"
VERMELHO = "#E02424"
CINZA = "#777777"
BORDA = "#e0e0e0"

# Faixas do 5Star, iguais às do painel.
FAIXA_5STAR_BOA = 4.50
FAIXA_5STAR_ATENCAO = 4.40

MESES_EXTENSO = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


# ==========================================================================
# AGREGAÇÃO (uma passada, cacheada)
# ==========================================================================
def _zerado():
    return {'total': 0, 'prom': 0, 'neu': 0, 'det': 0,
            'soma_5s': 0.0, 'n_5s': 0, 'motivos': Counter()}


def periodos_disponiveis(df_geral):
    """Meses presentes na base, do mais recente para o mais antigo."""
    if df_geral is None or df_geral.empty or 'Mes_Ano_Sort' not in df_geral.columns:
        return []
    return sorted(df_geral['Mes_Ano_Sort'].dropna().unique(), reverse=True)


def mes_anterior_a(mes, disponiveis):
    ordenados = sorted(disponiveis)
    if mes not in ordenados:
        return None
    pos = ordenados.index(mes)
    return ordenados[pos - 1] if pos > 0 else None


@st.cache_data(show_spinner="Calculando indicadores das franquias...")
def agregar_por_franquia(df_geral, df_class, mes_atual, mes_ref):
    """
    Contadores por (franquia, mês) numa única passada.

    Devolve {franquia: {mes: contadores}}. Os contadores são aditivos de
    propósito: somar os de várias franquias dá o consolidado correto, o que
    dispensa refiltrar o DataFrame por usuário.
    """
    meses = [m for m in (mes_atual, mes_ref) if m]
    agregado = {}

    def celula(fr, mes):
        return agregado.setdefault(fr, {}).setdefault(mes, _zerado())

    g = df_geral[df_geral['Mes_Ano_Sort'].isin(meses)]
    if not g.empty:
        g = g.assign(_fr=g['Franquia'].astype(str).str.strip())
        validos = g[g['NPS Purificador BTP'].notna()]

        # Vetorizado: uma tabela cruzada em vez de laço por grupo.
        if not validos.empty:
            ct = pd.crosstab([validos['_fr'], validos['Mes_Ano_Sort']],
                             validos['Classificacao'])
            for classe in ('Promotor', 'Neutro', 'Detrator'):
                if classe not in ct.columns:
                    ct[classe] = 0
            for (fr, mes), linha in ct.iterrows():
                c = celula(fr, mes)
                c['prom'] = int(linha['Promotor'])
                c['neu'] = int(linha['Neutro'])
                c['det'] = int(linha['Detrator'])
                c['total'] = c['prom'] + c['neu'] + c['det']

        if 'Avaliação do Técnico' in g.columns:
            notas = g.groupby(['_fr', 'Mes_Ano_Sort'])['Avaliação do Técnico'].agg(['sum', 'count'])
            for (fr, mes), linha in notas.iterrows():
                if linha['count']:
                    c = celula(fr, mes)
                    c['soma_5s'] = float(linha['sum'])
                    c['n_5s'] = int(linha['count'])

    # Motivos vêm da base classificada, que já contém só detratores e neutros.
    if (df_class is not None and not df_class.empty
            and 'Subcategorização Primária' in df_class.columns
            and 'Mes_Ano_Sort' in df_class.columns):
        cl = df_class[df_class['Mes_Ano_Sort'].isin(meses)]
        if not cl.empty:
            cl = cl.assign(
                _fr=cl['Franquia'].astype(str).str.strip(),
                _mot=cl['Subcategorização Primária'].astype(str).str.strip(),
            )
            contagem = cl.groupby(['_fr', 'Mes_Ano_Sort', '_mot'], sort=False).size()
            for (fr, mes, mot), qtd in contagem.items():
                celula(fr, mes)['motivos'][mot] = int(qtd)

    return agregado


def _somar(agregado, franquias, mes):
    """Soma os contadores das franquias do usuário num dado mês."""
    total = _zerado()
    if not mes:
        return total
    for fr in franquias:
        c = agregado.get(fr, {}).get(mes)
        if not c:
            continue
        for chave in ('total', 'prom', 'neu', 'det', 'soma_5s', 'n_5s'):
            total[chave] += c[chave]
        total['motivos'].update(c['motivos'])
    return total


def _metricas(c):
    """Converte contadores em indicadores. None quando não há base."""
    if c['total'] == 0:
        return {'volume': 0, 'nps': None, 'promotor': None, 'neutro': None,
                'detrator': None, 'cinco_star': None, 'motivos': []}
    return {
        'volume': c['total'],
        'nps': (c['prom'] - c['det']) / c['total'] * 100,
        'promotor': c['prom'] / c['total'] * 100,
        'neutro': c['neu'] / c['total'] * 100,
        'detrator': c['det'] / c['total'] * 100,
        'cinco_star': (c['soma_5s'] / c['n_5s']) if c['n_5s'] else None,
        'motivos': c['motivos'].most_common(),
    }


def montar_pacote(agregado, franquias, mes_atual, mes_ref):
    """Pacote de um usuário. Aritmética de dicionários — não toca no DataFrame."""
    pacote = {
        'consolidado': {
            'atual': _metricas(_somar(agregado, franquias, mes_atual)),
            'anterior': _metricas(_somar(agregado, franquias, mes_ref)),
        },
        'franquias': [],
    }
    for fr in sorted(franquias):
        atual = _metricas(_somar(agregado, [fr], mes_atual))
        anterior = _metricas(_somar(agregado, [fr], mes_ref))
        if atual['volume'] == 0 and anterior['volume'] == 0:
            continue
        pacote['franquias'].append({'nome': fr, 'atual': atual, 'anterior': anterior})
    return pacote


# ==========================================================================
# FORMATAÇÃO
# ==========================================================================
def _num(valor, casas=1, sufixo=""):
    if valor is None:
        return "—"
    return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".") + sufixo


def _inteiro(valor):
    if valor is None:
        return "—"
    return f"{int(valor):,}".replace(",", ".")


def _variacao(atual, anterior, casas=1, sufixo="", maior_e_melhor=True):
    """
    (texto, cor) da variação. Em Detratores subir é ruim, então
    maior_e_melhor=False inverte a cor — nunca o sinal.
    """
    if atual is None or anterior is None:
        return "sem base de comparação", CINZA
    delta = atual - anterior
    if abs(delta) < 0.05:
        return "estável", CINZA
    seta = "&#9650;" if delta > 0 else "&#9660;"
    bom = (delta > 0) if maior_e_melhor else (delta < 0)
    return f"{seta} {_num(abs(delta), casas, sufixo)}", (VERDE if bom else VERMELHO)


def _cor_5star(valor):
    if valor is None:
        return CINZA
    if valor >= FAIXA_5STAR_BOA:
        return VERDE
    if valor >= FAIXA_5STAR_ATENCAO:
        return AMBAR
    return VERMELHO


def _barra(rotulo, percentual, cor, valor_txt=None):
    """Barra proporcional em tabela — sobrevive ao motor do Word."""
    largura = max(min(percentual or 0, 100), 0)
    direita = valor_txt if valor_txt is not None else f"{_num(percentual)}%"
    return f"""
    <tr>
      <td style="padding:5px 0;font-size:12px;color:#333333;width:150px;">{rotulo}</td>
      <td style="padding:5px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td bgcolor="#eef1f6" style="background-color:#eef1f6;border-radius:3px;">
              <table role="presentation" width="{largura:.0f}%" cellpadding="0" cellspacing="0" border="0">
                <tr><td bgcolor="{cor}" style="background-color:{cor};height:8px;line-height:8px;font-size:0;border-radius:3px;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
      <td style="padding:5px 0 5px 10px;font-size:12px;color:#333333;text-align:right;width:56px;font-weight:bold;">{direita}</td>
    </tr>"""


def _card(titulo, valor, variacao_txt, variacao_cor, cor_valor=AZUL):
    return f"""
    <td width="50%" valign="top" style="padding:6px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="border:1px solid {BORDA};border-radius:6px;">
        <tr><td style="padding:12px 14px;">
          <div style="font-size:11px;color:{CINZA};text-transform:uppercase;letter-spacing:.5px;">{titulo}</div>
          <div style="font-size:26px;font-weight:bold;color:{cor_valor};padding:2px 0;">{valor}</div>
          <div style="font-size:12px;color:{variacao_cor};font-weight:bold;">{variacao_txt}</div>
        </td></tr>
      </table>
    </td>"""


def _titulo_secao(texto):
    return (f'<div style="font-size:13px;font-weight:bold;color:#333333;'
            f'margin:24px 0 6px 0;">{texto}</div>')


# ==========================================================================
# BLOCOS DO E-MAIL
# ==========================================================================
def _rotulo_mes(mes):
    try:
        ano, num = str(mes).split('-')[:2]
        return f"{MESES_EXTENSO.get(int(num), num)} de {ano}"
    except Exception:
        return str(mes)


def _bloco_cartoes(atual, anterior):
    v_nps, c_nps = _variacao(atual['nps'], anterior['nps'])
    v_vol, c_vol = _variacao(atual['volume'], anterior['volume'], casas=0)
    v_det, c_det = _variacao(atual['detrator'], anterior['detrator'],
                             sufixo=" p.p.", maior_e_melhor=False)
    v_est, c_est = _variacao(atual['cinco_star'], anterior['cinco_star'], casas=2)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        {_card("NPS do mês", _num(atual['nps']), v_nps, c_nps)}
        {_card("Respostas", _inteiro(atual['volume']), v_vol, c_vol)}
      </tr>
      <tr>
        {_card("Detratores", _num(atual['detrator'], sufixo="%"), v_det, c_det)}
        {_card("5Star — nota do técnico", _num(atual['cinco_star'], casas=2), v_est, c_est,
               cor_valor=_cor_5star(atual['cinco_star']))}
      </tr>
    </table>"""


def _bloco_5star(atual):
    """Faixa do 5Star, com o mesmo critério do painel."""
    valor = atual['cinco_star']
    if valor is None:
        return ""
    cor = _cor_5star(valor)
    if valor >= FAIXA_5STAR_BOA:
        leitura = "dentro da meta"
    elif valor >= FAIXA_5STAR_ATENCAO:
        leitura = "em zona de atenção"
    else:
        leitura = "abaixo do esperado"
    largura = max(min(valor / 5 * 100, 100), 0)

    return f"""
    {_titulo_secao("5Star — avaliação do técnico")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="border:1px solid {BORDA};border-radius:6px;">
      <tr><td style="padding:14px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="font-size:30px;font-weight:bold;color:{cor};width:90px;">{_num(valor, 2)}</td>
            <td style="font-size:12px;color:#333333;">
              de 5,0 — <span style="color:{cor};font-weight:bold;">{leitura}</span>
              <div style="font-size:11px;color:{CINZA};margin-top:2px;">
                Meta: 4,50 &nbsp;|&nbsp; Atenção: 4,40 a 4,49
              </div>
            </td>
          </tr>
        </table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:10px;">
          <tr>
            <td bgcolor="#eef1f6" style="background-color:#eef1f6;border-radius:3px;">
              <table role="presentation" width="{largura:.0f}%" cellpadding="0" cellspacing="0" border="0">
                <tr><td bgcolor="{cor}" style="background-color:{cor};height:8px;line-height:8px;font-size:0;border-radius:3px;">&nbsp;</td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>"""


def _bloco_motivos(atual):
    """Principais motivos de detratores e neutros, como na aba do painel."""
    motivos = atual.get('motivos') or []
    if not motivos:
        return ""
    top = motivos[:TOP_MOTIVOS]
    total = sum(qtd for _, qtd in motivos)
    linhas = "".join(
        _barra(nome, (qtd / total * 100) if total else 0, AZUL, valor_txt=_inteiro(qtd))
        for nome, qtd in top
    )
    restante = len(motivos) - len(top)
    nota = (f'<div style="font-size:11px;color:{CINZA};margin-top:6px;">'
            f'Mais {restante} motivo(s) fora do top {TOP_MOTIVOS}.</div>') if restante > 0 else ""

    return f"""
    {_titulo_secao("Principais motivos de detratores e neutros")}
    <div style="font-size:11px;color:{CINZA};margin:-2px 0 8px 0;">
      Base: {_inteiro(total)} manifestação(ões) classificada(s) no mês.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      {linhas}
    </table>
    {nota}"""


def _bloco_composicao(atual):
    return f"""
    {_titulo_secao("Composição das respostas")}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      {_barra("Promotores", atual['promotor'], VERDE)}
      {_barra("Neutros", atual['neutro'], AMBAR)}
      {_barra("Detratores", atual['detrator'], VERMELHO)}
    </table>"""


def _tabela_franquias(franquias):
    """
    Franquias com resposta, da maior para a menor.

    Quem tem muitas franquias (há casos de 37) recebia uma tabela cheia de
    linhas zeradas, o que enterrava as que importam. As sem resposta saem da
    tabela e viram uma linha de texto ao final — a informação continua lá,
    sem competir com o que tem número.
    """
    com_dados = [f for f in franquias if f['atual']['volume'] > 0]
    sem_dados = [f['nome'] for f in franquias if f['atual']['volume'] == 0]
    com_dados.sort(key=lambda f: (-f['atual']['volume'], f['nome']))

    linhas = []
    for item in com_dados:
        a, p = item['atual'], item['anterior']
        var_txt, var_cor = _variacao(a['nps'], p['nps'])
        estrela = _num(a['cinco_star'], 2)
        linhas.append(f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid {BORDA};font-size:12px;color:#333333;">{item['nome']}</td>
          <td style="padding:9px 10px;border-bottom:1px solid {BORDA};font-size:12px;color:#333333;text-align:right;font-weight:bold;">{_num(a['nps'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid {BORDA};font-size:12px;color:{var_cor};text-align:right;">{var_txt}</td>
          <td style="padding:9px 10px;border-bottom:1px solid {BORDA};font-size:12px;color:{_cor_5star(a['cinco_star'])};text-align:right;">{estrela}</td>
          <td style="padding:9px 10px;border-bottom:1px solid {BORDA};font-size:12px;color:#333333;text-align:right;">{_inteiro(a['volume'])}</td>
        </tr>""")

    cab = ('padding:9px 10px;font-size:11px;color:%s;text-transform:uppercase;'
           'border-bottom:1px solid %s;' % (CINZA, BORDA))

    if not linhas:
        tabela = (f'<div style="font-size:12px;color:{CINZA};">'
                  f'Nenhuma das suas franquias teve respostas no mês.</div>')
    else:
        tabela = f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="border:1px solid {BORDA};border-radius:6px;">
      <tr bgcolor="#f8f9fa" style="background-color:#f8f9fa;">
        <th align="left" style="{cab}">Franquia</th>
        <th align="right" style="{cab}">NPS</th>
        <th align="right" style="{cab}">vs. mês ant.</th>
        <th align="right" style="{cab}">5Star</th>
        <th align="right" style="{cab}">Respostas</th>
      </tr>
      {''.join(linhas)}
    </table>"""

    nota = ""
    if sem_dados:
        nota = (f'<div style="font-size:11px;color:{CINZA};margin-top:8px;">'
                f'<b>{len(sem_dados)} franquia(s) sem respostas no mês:</b> '
                f'{", ".join(sorted(sem_dados))}.</div>')

    return _titulo_secao("Detalhe por franquia") + tabela + nota


def montar_html(nome, pacote, mes_atual, mes_ref):
    """E-mail completo. Estrutura e paleta espelham o padrão do Massivo."""
    primeiro_nome = str(nome).strip().split(' ')[0].title()
    consolidado = pacote['consolidado']
    atual = consolidado['atual']
    varias = len(pacote['franquias']) > 1

    if atual['volume'] == 0:
        abertura = (f"Não houve respostas de pesquisa registradas para as suas franquias "
                    f"em {_rotulo_mes(mes_atual)}.")
        miolo = ""
    else:
        abertura = (f"Segue o resumo de NPS das suas franquias em "
                    f"<b>{_rotulo_mes(mes_atual)}</b>, comparado a {_rotulo_mes(mes_ref)}."
                    if mes_ref else
                    f"Segue o resumo de NPS das suas franquias em <b>{_rotulo_mes(mes_atual)}</b>.")
        miolo = (_bloco_cartoes(atual, consolidado['anterior'])
                 + _bloco_composicao(atual)
                 + _bloco_5star(atual)
                 + _bloco_motivos(atual)
                 + (_tabela_franquias(pacote['franquias']) if varias else ""))

    titulo_consolidado = ("Consolidado das suas franquias" if varias
                          else "Resultado da sua franquia")
    cabecalho_secao = _titulo_secao(titulo_consolidado) if atual['volume'] else ""

    return f"""<div style="font-family: Arial, sans-serif; color: #333333; max-width: 600px; border: 1px solid {BORDA}; border-radius: 8px; overflow: hidden; margin: 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="background-color: #ffffff;">
        <tr>
            <td align="center" bgcolor="#ffffff" style="background-color: #ffffff; padding: 0;">
                <img src="{BANNER_URL}" alt="Brastemp by Culligan" width="600" style="width: 100%; max-width: 600px; height: auto; display: block; margin: 0 auto; border: 0;">
            </td>
        </tr>
    </table>
    <div style="background-color: {AZUL}; padding: 15px 20px; text-align: center; color: #ffffff;">
        <h2 style="margin: 0; font-size: 18px; font-weight: normal;">NPS Franquias &mdash; {_rotulo_mes(mes_atual).title()}</h2>
    </div>
    <div style="padding: 20px;">
        <p style="margin-top: 0;">Olá, <b>{primeiro_nome}</b>!</p>
        <p>{abertura}</p>
        {cabecalho_secao}
        {miolo}
        <p style="font-size: 12px; color: {CINZA}; margin-top: 26px; border-top: 1px solid {BORDA}; padding-top: 15px;">
            <em><strong>Atenção:</strong> Por favor, não responda a este e-mail. Esta é uma mensagem
            automática. O NPS considera as respostas de pesquisa recebidas no período; a variação
            compara o mês atual com o mês imediatamente anterior. Os motivos vêm das manifestações
            de detratores e neutros classificadas no mês.</em>
        </p>
        <br>
        <p style="margin: 0;">Atenciosamente,</p>
        <p style="margin: 4px 0 0 0; color: {AZUL};"><strong>Equipe de Experiência do Cliente</strong></p>
        <p style="margin: 0; font-size: 12px; color: {CINZA};">Purificadores de Água Brastemp by Culligan</p>
    </div>
</div>"""


# ==========================================================================
# TRANSPORTE (OUTLOOK COM)
# ==========================================================================
def outlook_disponivel():
    """(disponível, motivo). Falso no Streamlit Cloud, que roda em Linux."""
    import sys
    if not sys.platform.startswith("win"):
        return False, ("Este ambiente não é Windows (o painel está na nuvem). "
                       "O disparo usa o Outlook instalado e só funciona rodando local.")
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
    except ImportError:
        return False, ("O pacote pywin32 não está instalado. "
                       "No prompt, rode: pip install pywin32")
    return True, ""


def enviar_via_outlook(para, assunto, corpo_html):
    """
    Envia pelo Outlook clássico logado, sem SMTP. Adaptado do projeto Massivo.

    O COM precisa ser inicializado na thread que fala com o Outlook, senão dá
    "CoInitialize não foi chamado" (-2147221008).
    """
    import win32com.client as win32
    import pythoncom

    com_iniciado = False
    try:
        pythoncom.CoInitialize()
        com_iniciado = True
    except Exception:
        pass

    try:
        try:
            outlook = win32.Dispatch("Outlook.Application")
        except Exception as e:
            raise RuntimeError(
                "Não consegui falar com o Outlook. Confirme que o Outlook clássico "
                f"está instalado e aberto neste PC. Detalhe: {e}")

        try:
            mail = outlook.CreateItem(0)          # 0 = olMailItem
            mail.To = para
            mail.Subject = assunto
            mail.HTMLBody = corpo_html

            if EMAIL_DE:
                mail.SentOnBehalfOfName = EMAIL_DE

            if EMAIL_CONTA:
                try:
                    contas = outlook.Session.Accounts
                    escolhida = None
                    for i in range(1, contas.Count + 1):
                        ac = contas.Item(i)
                        if str(getattr(ac, "SmtpAddress", "")).lower() == EMAIL_CONTA.lower():
                            escolhida = ac
                            break
                    if escolhida is not None:
                        mail._oleobj_.Invoke(*(64209, 0, 8, 0, escolhida))
                except Exception:
                    pass   # sem a conta específica, sai pela conta padrão

            mail.Send()
        except Exception as e:
            det = str(e)
            baixo = det.lower()
            dica = ""
            if "rpc" in baixo or "0x800706" in baixo or "call was rejected" in baixo:
                dica = (" — o Outlook parece fechado ou ocupado. Abra o Outlook clássico "
                        "e deixe-o rodando durante o disparo.")
            elif "denied" in baixo or "negado" in baixo or "0x80070005" in baixo:
                dica = (" — envio bloqueado pela segurança do Outlook. Se aparecer um aviso "
                        "pedindo permissão, clique em Permitir.")
            raise RuntimeError(f"Outlook não enviou: {det}{dica}")
    finally:
        if com_iniciado:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


# ==========================================================================
# INTERFACE DA ABA
# ==========================================================================
@st.cache_data(ttl=120, show_spinner=False)
def _vinculos_por_usuario():
    """
    Todos os vínculos usuário -> franquia numa consulta só.

    Antes era uma consulta por usuário: 31 idas ao Neon a cada rerun do painel.
    """
    from auth import run_query
    df = run_query("SELECT usuario_id, franquia FROM nps_usuario_franquias",
                   ttl=0, spinner="Carregando vínculos de franquia...")
    if df.empty:
        return {}
    from franquias import unificar_lista
    df['franquia'] = df['franquia'].astype(str).str.strip()
    return {int(uid): unificar_lista(grupo['franquia'].tolist())
            for uid, grupo in df.groupby('usuario_id')}


@st.cache_data(ttl=120, show_spinner=False)
def _destinatarios():
    """Usuários comuns ativos."""
    from auth import run_query
    return run_query("""
        SELECT id, usuario, nome, email
          FROM nps_usuarios
         WHERE tipo = 'comum' AND ativo = TRUE
         ORDER BY nome
    """, ttl=0, spinner="Carregando destinatários...")


def render_comunicacao(df_geral, df_class):
    """Aba 'Comunicação Franquias'. Só é chamada para administradores."""
    st.subheader("Comunicação Franquias")
    st.caption(
        "Envia a cada franqueado os indicadores das franquias dele: consolidado, "
        "composição, 5Star, principais motivos e a quebra por franquia."
    )
    _corpo_comunicacao(df_geral, df_class)


# st.fragment isola os reruns: mexer no seletor de mês, nas caixas de seleção
# ou na prévia reexecuta só este bloco, não o painel inteiro.
@st.fragment
def _corpo_comunicacao(df_geral, df_class):
    from auth import registrar_log

    disponivel, motivo = outlook_disponivel()
    if not disponivel:
        st.warning(f"**Disparo indisponível neste ambiente.** {motivo}")
        st.caption("A prévia continua funcionando; o disparo você faz rodando o painel local.")

    meses = periodos_disponiveis(df_geral)
    if not meses:
        st.info("Não há dados de NPS carregados para montar a comunicação.")
        return

    c1, c2 = st.columns([1, 2])
    with c1:
        mes_atual = st.selectbox("Mês de referência", meses, index=0,
                                 format_func=_rotulo_mes, key="com_mes",
                                 help="O mês mais recente da base já vem selecionado.")
    mes_ref = mes_anterior_a(mes_atual, meses)
    with c2:
        st.write("")
        st.caption(f"Comparando **{_rotulo_mes(mes_atual)}** com **{_rotulo_mes(mes_ref)}**."
                   if mes_ref else "Primeiro mês da base: o e-mail sai sem variação.")

    agregado = agregar_por_franquia(df_geral, df_class, mes_atual, mes_ref)
    vinculos = _vinculos_por_usuario()
    df_dest = _destinatarios()

    if df_dest.empty:
        st.info("Nenhum usuário comum ativo cadastrado.")
        return

    linhas, pacotes = [], {}
    for _, u in df_dest.iterrows():
        uid = int(u['id'])
        franquias = vinculos.get(uid, [])
        pacotes[uid] = montar_pacote(agregado, franquias, mes_atual, mes_ref)
        cons = pacotes[uid]['consolidado']['atual']
        email = str(u['email'] or '').strip()
        linhas.append({
            'Enviar': False,          # preenchido logo abaixo, a partir do estado
            'id': uid,
            'Nome': u['nome'],
            'E-mail': email or '(sem e-mail)',
            'Franquias': len(franquias),
            'Respostas': cons['volume'],
            'NPS': round(cons['nps'], 1) if cons['nps'] is not None else None,
        })

    df_linhas = pd.DataFrame(linhas)
    tem_email = df_linhas['E-mail'].str.contains('@')
    elegivel = tem_email & (df_linhas['Respostas'] > 0)

    sem_email = int((~tem_email).sum())
    if sem_email:
        st.warning(f"{sem_email} usuário(s) sem e-mail cadastrado ficam fora do disparo.")

    # A seleção é estado próprio, não coluna recalculada.
    #
    # O st.data_editor guarda apenas o DELTA contra o DataFrame que recebe. Antes,
    # a coluna 'Enviar' era remontada com todos marcados por padrão a cada rerun;
    # depois de "Desmarcar todos", o primeiro clique numa linha reexecutava o
    # bloco, o DataFrame voltava com todos True e o delta de um único clique era
    # aplicado por cima — a seleção inteira ressuscitava.
    chave_sel = f"com_sel_{mes_atual}"
    if chave_sel not in st.session_state:
        st.session_state[chave_sel] = dict(zip(df_linhas['id'], elegivel))

    st.markdown("---")
    ca, cb, _cc = st.columns([1, 1, 3])

    def _redefinir(marcar_todos):
        st.session_state[chave_sel] = {
            int(uid): (bool(marcar_todos) and bool(ok))
            for uid, ok in zip(df_linhas['id'], tem_email)
        }
        # Versiona a chave do editor: instância nova nasce sem delta antigo.
        st.session_state['com_editor_v'] = st.session_state.get('com_editor_v', 0) + 1

    with ca:
        if st.button("Marcar todos", use_container_width=True, key="com_marcar"):
            _redefinir(True)
            st.rerun(scope="fragment")
    with cb:
        if st.button("Desmarcar todos", use_container_width=True, key="com_desmarcar"):
            _redefinir(False)
            st.rerun(scope="fragment")

    selecao = st.session_state[chave_sel]
    df_linhas['Enviar'] = [bool(selecao.get(int(u), False)) for u in df_linhas['id']]

    editado = st.data_editor(
        df_linhas, use_container_width=True, hide_index=True,
        key=f"com_editor_{st.session_state.get('com_editor_v', 0)}",
        column_config={
            'Enviar': st.column_config.CheckboxColumn('Enviar', default=False),
            'id': None,
            'Nome': st.column_config.TextColumn('Nome'),
            'E-mail': st.column_config.TextColumn('E-mail'),
            'Franquias': st.column_config.NumberColumn('Franquias', format='%d'),
            'Respostas': st.column_config.NumberColumn('Respostas', format='%d'),
            'NPS': st.column_config.NumberColumn('NPS', format='%.1f'),
        },
        disabled=['Nome', 'E-mail', 'Franquias', 'Respostas', 'NPS'],
    )

    # Persiste o que o usuário deixou marcado, para o próximo rerun partir daqui.
    st.session_state[chave_sel] = {int(r['id']): bool(r['Enviar'])
                                   for _, r in editado.iterrows()}

    selecionados = editado[editado['Enviar'] & editado['E-mail'].str.contains('@')]

    # --- Prévia ---
    st.markdown("---")
    st.markdown("#### Prévia do e-mail")
    nomes = {f"{r['Nome']} — {int(r['Franquias'])} franquia(s)": int(r['id'])
             for _, r in df_linhas.iterrows()}
    escolhido = st.selectbox("Visualizar o e-mail de:", list(nomes.keys()), key="com_previa")
    uid_prev = nomes[escolhido]
    nome_prev = df_linhas[df_linhas['id'] == uid_prev].iloc[0]['Nome']
    html_prev = montar_html(nome_prev, pacotes[uid_prev], mes_atual, mes_ref)
    st.components.v1.html(html_prev, height=900, scrolling=True)

    with st.expander("Ver o HTML gerado"):
        st.code(html_prev, language="html")

    # --- Disparo ---
    st.markdown("---")
    st.markdown(f"**{len(selecionados)} destinatário(s) selecionado(s).**")
    assunto = st.text_input("Assunto", key="com_assunto",
                            value=f"NPS Franquias - resultado de {_rotulo_mes(mes_atual)}")

    if not disponivel:
        st.button("Disparar e-mails", disabled=True, use_container_width=True,
                  help=motivo, key="com_disparar_off")
        return

    confirmar = st.checkbox(
        f"Confirmo o envio para {len(selecionados)} franqueado(s), a partir de {EMAIL_DE}.",
        key="com_confirma")

    if st.button("Disparar e-mails", type="primary", use_container_width=True,
                 disabled=(not confirmar or selecionados.empty), key="com_disparar"):
        barra = st.progress(0.0, text="Iniciando...")
        resultados = []
        total = len(selecionados)

        for i, (_, r) in enumerate(selecionados.iterrows(), start=1):
            uid = int(r['id'])
            destino = str(r['E-mail']).strip()
            try:
                enviar_via_outlook(destino, assunto,
                                   montar_html(r['Nome'], pacotes[uid], mes_atual, mes_ref))
                resultados.append({'Nome': r['Nome'], 'E-mail': destino,
                                   'Status': 'Enviado', 'Detalhe': ''})
            except Exception as e:
                resultados.append({'Nome': r['Nome'], 'E-mail': destino,
                                   'Status': 'Falhou', 'Detalhe': str(e)[:300]})

            barra.progress(i / total, text=f"{i} de {total} — {r['Nome']}")
            if i < total and PAUSA_ENTRE_ENVIOS_S:
                time.sleep(PAUSA_ENTRE_ENVIOS_S)

        barra.empty()
        df_res = pd.DataFrame(resultados)
        enviados = int((df_res['Status'] == 'Enviado').sum())
        falhas = len(df_res) - enviados

        if falhas == 0:
            st.success(f"{enviados} e-mail(s) enviado(s).")
        else:
            st.warning(f"{enviados} enviado(s), {falhas} com falha.")
        st.dataframe(df_res, use_container_width=True, hide_index=True)

        registrar_log("Comunicação Franquias",
                      f"mes={mes_atual} enviados={enviados} falhas={falhas}")
        st.caption(
            "O Outlook envia de forma assíncrona: as mensagens vão para a Caixa de Saída "
            "e o Exchange despacha no ritmo dele. Confira em Itens Enviados."
        )
