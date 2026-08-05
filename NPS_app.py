import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import os
from io import BytesIO

# 1. Configuração da Página
st.set_page_config(
    page_title="NPS - Franquias",
    page_icon="📊",
    layout="wide"
)

# ==========================================================================
# AUTENTICAÇÃO
# Precisa vir antes de qualquer renderização: exigir_login() interrompe o
# script (st.stop) enquanto não houver usuário autenticado com 2FA validado.
# ==========================================================================
import auth
from admin_usuarios import render_admin_usuarios
from comunicacao import render_comunicacao
from franquias import unificar_serie

auth.exigir_login()

# Perfis: admin (tudo), operacao (ve tudo, aba Usuarios em leitura),
# comum (apenas as franquias vinculadas ao seu cadastro).
VE_TODAS_FRANQUIAS = auth.ve_todas_franquias()
PODE_EDITAR_USUARIOS = auth.pode_editar_usuarios()

# --- AJUSTES DE INTERFACE PÓS-LOGIN ---
st.markdown("""
<style>
/* Esconde o indicador "Running..." do Streamlit. No lugar dele, cada consulta
   ao banco mostra um spinner próprio (ver auth.run_query). */
[data-testid="stStatusWidget"] { display: none !important; }

/* Devolve o cabeçalho, que auth.exigir_login() escondeu para a tela de login. */
[data-testid="stHeader"], [data-testid="stToolbar"] { display: flex !important; }

/* Botões "Senha" e "Sair" do menu lateral: fundo azul, fonte branca. */
[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    background-color: #1E5FCC !important;
    border: none !important;
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"] *,
[data-testid="stSidebar"] .stButton > button[kind="secondary"] p {
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
    background-color: #0A2A66 !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================================================
# TEMA VISUAL CORPORATIVO PREMIUM (CSS)
# ==========================================================================
CUSTOM_CSS = """
<style>
/* ---- Fonte Limpa e Moderna (Poppins) ---- */
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap');

/* ---- Paleta corporativa ---- */
:root {
    --navy:      #0A2A66;
    --blue:      #1E5FCC;
    --blue2:     #3B82F6;
    --blue-soft: #EAF1FB;
    --ink:       #16233F;
    --muted:     #647393;
    --line:      #E4EBF6;
    --bg:        #F4F7FD;
    --card:      #FFFFFF;
    --pos:       #0E9F6E;
    --neg:       #E02424;
}

/* ---- Escala raiz e fonte global ---- */
html { font-size: 13px; }
html, body, .stApp, [class*="css"] {
    font-family: 'Poppins', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--ink);
}

/* ---- Fundo geral do app ---- */
.stApp,
[data-testid="stAppViewContainer"] { background: var(--bg); }

/* ---- Esconde header/menu/footer nativos ---- */
header[data-testid="stHeader"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stAppViewContainer"] > .main .block-container,
[data-testid="stMainBlockContainer"] { padding-top: 2rem; }

/* ---- Títulos (menores e em negrito) ---- */
h1 { font-size: 1.5rem !important; }
h2 { font-size: 1.25rem !important; }
h3 { font-size: 1.05rem !important; }
h1, h2, h3 {
    color: var(--navy) !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em !important;
}
h4, h5, h6 { color: var(--ink) !important; font-weight: 600 !important; }

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background: var(--card);
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] * { color: var(--ink); }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: var(--navy) !important; }
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown p { color: var(--muted); }

/* ---- KPI Cards (premium) ---- */
.kpi-card {
    position: relative;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 10px 8px; /* Reduzido para encaixar melhor a fonte nova */
    height: 85px; /* Altura ajustada para o tamanho menor e clean da fonte */
    width: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(16,40,90,.04), 0 6px 16px rgba(16,40,90,.05);
    transition: transform .18s ease, box-shadow .18s ease;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(16,40,90,.08), 0 12px 24px rgba(16,40,90,.10);
}
.kpi-topbar {
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, var(--navy), var(--blue2));
}

/* Textos do KPI */
.kpi-title {
    font-size: 11px; 
    font-weight: 700 !important; 
    color: var(--muted);
    letter-spacing: 0.2px; margin: 0 0 4px 0; 
    line-height: 1.2; overflow-wrap: normal; word-break: normal;
}
.kpi-value {
    font-size: 18px !important; /* Agora sim, um meio termo elegante e corporativo */
    font-weight: 700 !important; /* Bold padrão, sem exageros */
    color: var(--navy);
    margin: 2px 0; 
    line-height: 1;
}
.kpi-sub {
    font-size: 10px; font-weight: 500; color: var(--muted);
    margin: 4px 0 0 0; 
    line-height: 1;
}

/* ---- Card de destaque (dark / hero) ---- */
.kpi-dark {
    background: linear-gradient(180deg, #0A2A66 0%, #163D8C 100%);
    border: 1px solid #0A2A66;
    box-shadow: 0 2px 6px rgba(10,42,102,.20), 0 14px 30px rgba(10,42,102,.25);
}
.kpi-dark .kpi-title { color: #B9CCEF; }
.kpi-dark .kpi-value { color: #FFFFFF; }
.kpi-dark .kpi-sub { color: #A0BCE0; }
.kpi-dark:hover {
    box-shadow: 0 6px 12px rgba(10,42,102,.28), 0 20px 40px rgba(10,42,102,.32);
}

/* ---- Classes Dinâmicas (Tons Pastéis Premium) para 5Star ---- */
.kpi-bg-green { background-color: #e6f4ea !important; border-color: #ceead6 !important; }
.kpi-bg-yellow { background-color: #fef7e0 !important; border-color: #fde293 !important; }
.kpi-bg-red { background-color: #fce8e6 !important; border-color: #fad2cf !important; }
.kpi-bg-green .kpi-value, .kpi-bg-yellow .kpi-value, .kpi-bg-red .kpi-value { color: var(--navy) !important; }

/* ---- Cartões de composição NPS (Promotores / Neutros / Detratores) ---- */
.cat-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
    margin: 2px 0 16px 0;
}
.cat-card {
    position: relative;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 13px 15px 14px 18px;
    overflow: hidden;
}
.cat-card::before {
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    background: var(--cat);
}
.cat-head { display: flex; align-items: center; gap: 7px; }
.cat-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--cat); flex: none; }
.cat-name {
    font-size: 10.5px; font-weight: 700; letter-spacing: .09em;
    text-transform: uppercase; color: var(--muted); white-space: nowrap;
}
.cat-value {
    font-size: 27px; font-weight: 800; color: var(--navy);
    line-height: 1.12; margin-top: 5px; font-variant-numeric: tabular-nums;
}
.cat-sub { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.cat-sub b { color: var(--cat); font-weight: 700; font-variant-numeric: tabular-nums; }
.cat-bar { height: 5px; border-radius: 3px; background: var(--line); margin-top: 10px; overflow: hidden; }
.cat-bar > i { display: block; height: 100%; border-radius: 3px; background: var(--cat); }

@media only screen and (max-width: 640px) {
    .cat-grid { grid-template-columns: 1fr; }
}

/* ---- Botões (primário e download) ---- */
.stButton > button, .stDownloadButton > button {
    background: var(--navy); color: #FFFFFF; border: none;
    border-radius: 9px; font-weight: 500; padding: 8px 18px;
    transition: background .15s ease, transform .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background: var(--blue); color: #FFFFFF; transform: translateY(-1px);
}
.stButton > button:focus, .stDownloadButton > button:focus { color: #FFFFFF; }

/* ---- Tabs ---- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 4px; border-bottom: 1px solid var(--line);
}
[data-testid="stTabs"] button[data-baseweb="tab"] {
    background: var(--blue-soft);
    border-radius: 8px 8px 0 0;
    padding: 8px 16px;
    color: var(--muted);
    border-bottom: 3px solid transparent;
    font-weight: 500;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    background: #FFFFFF;
    color: var(--navy) !important;
    border-bottom: 3px solid var(--blue);
}

/* ---- DataFrames / Tabelas ---- */
[data-testid="stDataFrame"], [data-testid="stTable"] {
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: 0 1px 2px rgba(16,40,90,.04), 0 6px 16px rgba(16,40,90,.04);
    overflow: hidden;
}

/* ---- Métricas nativas (caso existam) ---- */
[data-testid="stMetric"] {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 14px;
    box-shadow: 0 1px 2px rgba(16,40,90,.04), 0 6px 16px rgba(16,40,90,.05);
}

/* ---- Inputs / selects ---- */
[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input {
    border-radius: 8px !important;
    border-color: var(--line) !important;
}

/* ---- Divisores ---- */
hr { border-color: var(--line); }

/* ---- Logo da sidebar ---- */
.sidebar-logo { padding: 4px 0 10px 0; text-align: center; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ==========================================================================
# TEMA GLOBAL DOS GRÁFICOS (Plotly) - fundo transparente + fonte Poppins
# ==========================================================================
pio.templates["nps_premium"] = go.layout.Template(
    layout=dict(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family='Poppins, sans-serif', color='#16233F', size=12),
        title=dict(font=dict(family='Poppins, sans-serif', color='#0A2A66')),
        xaxis=dict(gridcolor='#E4EBF6', zerolinecolor='#E4EBF6', linecolor='#E4EBF6'),
        yaxis=dict(gridcolor='#E4EBF6', zerolinecolor='#E4EBF6', linecolor='#E4EBF6'),
        legend=dict(bgcolor='rgba(0,0,0,0)'),
    )
)
pio.templates.default = "plotly+nps_premium"

def fundo_transparente(fig):
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- PALETAS DE CORES ---
CORES_NPS_PASTEL = {
    'Promotor': '#a8e6cf', 
    'Neutro': '#fdffab',   
    'Detrator': '#ffaaa5'  
}

CORES_BLUES = [
    '#08306b', '#08519c', '#2171b5', '#4292c6', 
    '#6baed6', '#9ecae1', '#c6dbef', '#deebf7'
]

# Constantes de nomes de arquivo
ARQUIVO_GERAL = "NPS Geral.xlsx"
ARQUIVO_CLASSIFICADO = "NPS Classificado.xlsx"
ARQUIVO_DATA = "data_atualizacao.txt"

# Mapa Global de Meses para formatação
MAPA_MESES_GLOBAL = {
    1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun', 
    7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
}

# --- FUNÇÕES AUXILIARES GLOBAIS ---
def classificar_nps(nota):
    if pd.isna(nota): return "Sem Nota"
    if nota >= 9: return "Promotor"
    elif nota >= 7: return "Neutro"
    else: return "Detrator"

def normalizar_programa(val):
    if pd.isna(val): return val
    v = str(val).strip()
    v_low = v.lower()
    if 'instala' in v_low:
        return 'Instalação'
    if v_low in ('pós os', 'pos os', 'pós-os', 'pos-os'):
        return 'Pós OS'
    if v_low == 'maintenance':
        return 'Maintenance'
    if v_low in ('reparo', 'repair'):
        return 'Reparo'
    return v

def calcular_nps_score(df_input):
    if df_input.empty: return 0
    counts = df_input['Classificacao'].value_counts()
    total = len(df_input)
    if total == 0: return 0
    promotores = counts.get('Promotor', 0)
    detratores = counts.get('Detrator', 0)
    return ((promotores - detratores) / total) * 100

def fmt_milhar(valor):
    if pd.isna(valor): return "-"
    return f"{int(valor):,}".replace(",", ".")

def ler_data_atualizacao():
    if os.path.exists(ARQUIVO_DATA):
        with open(ARQUIVO_DATA, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "Data n/d"

def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    processed_data = output.getvalue()
    return processed_data

# 2. Funções de Carregamento
@st.cache_data
def load_data_geral(file_path):
    if not os.path.exists(file_path): return None
    try:
        df = pd.read_excel(file_path)
        cols_data = ['Data de criação local', 'Data da resposta local', 'Data']
        for col in cols_data:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
        
        if 'NPS Purificador BTP' in df.columns:
            df['NPS Purificador BTP'] = pd.to_numeric(df['NPS Purificador BTP'], errors='coerce')
        if 'Avaliação do Técnico' in df.columns:
            df['Avaliação do Técnico'] = pd.to_numeric(df['Avaliação do Técnico'], errors='coerce')
        if 'Num OS' in df.columns:
            df['Num OS'] = df['Num OS'].astype(str).str.replace('.0', '', regex=False)

        df['Classificacao'] = df['NPS Purificador BTP'].apply(classificar_nps)
        df['Mes_Ano_Sort'] = df['Data da resposta local'].dt.to_period('M').astype(str)
        df['Ano'] = df['Data da resposta local'].dt.year
        
        df['Mes_Num'] = df['Data da resposta local'].dt.month
        df['Mes_Nome'] = df['Mes_Num'].map(MAPA_MESES_GLOBAL)

        if 'Programa de Pesquisa' in df.columns:
            df['Programa Original'] = df['Programa de Pesquisa']
            df['Programa de Pesquisa'] = df['Programa de Pesquisa'].apply(normalizar_programa)

        if 'Forma Jurídica' in df.columns:
            def map_segmento(val):
                if pd.isna(val): return 'Não Informado'
                v_str = str(val).strip()
                if v_str == 'Não atribuído': return 'PF'
                if v_str == 'P1': return 'PME'
                if v_str == 'C1': return 'Corporativo'
                return v_str
            df['Segmento'] = df['Forma Jurídica'].apply(map_segmento)
        else:
            df['Segmento'] = 'Não Informado'

        if 'Plataforma' in df.columns:
            df['Plataforma'] = df['Plataforma'].astype(str).str.strip()
            df.loc[df['Plataforma'].isin(['nan', 'None', 'NaN', '']), 'Plataforma'] = 'Não Informado'
        else:
            df['Plataforma'] = 'Não Informado'

        # Unifica a franquia já na carga: remove a grade (R01/R02/MATRIZ) e
        # converte a nomenclatura antiga do Medallia via De-Para.xlsx. Como a
        # coluna é substituída aqui, todo o resto do painel — filtros, KPIs,
        # gráficos, e-mail — passa a trabalhar no nome unificado sem mudança.
        if 'Franquia' in df.columns:
            df['Franquia Original'] = df['Franquia']
            df['Franquia'] = unificar_serie(df['Franquia'])

        return df
    except Exception as e:
        st.error(f"Erro ao ler {file_path}: {e}")
        return None

@st.cache_data
def load_data_classificado(file_path):
    if not os.path.exists(file_path): return None
    try:
        df = pd.read_excel(file_path)
        if 'Data' in df.columns:
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)
            df['Mes_Ano_Sort'] = df['Data'].dt.to_period('M').astype(str)
            df['Ano'] = df['Data'].dt.year
            df['Mes_Num'] = df['Data'].dt.month
            df['Mes_Nome'] = df['Mes_Num'].map(MAPA_MESES_GLOBAL)
        
        if 'Num OS' in df.columns:
            df['Num OS'] = df['Num OS'].astype(str).str.replace('.0', '', regex=False)

        if 'Programa de Pesquisa' in df.columns:
            df['Programa Original'] = df['Programa de Pesquisa']
            df['Programa de Pesquisa'] = df['Programa de Pesquisa'].apply(normalizar_programa)

        if 'Plataforma' in df.columns:
            df['Plataforma'] = df['Plataforma'].astype(str).str.strip()
            df.loc[df['Plataforma'].isin(['nan', 'None', 'NaN', '']), 'Plataforma'] = 'Não Informado'

        if 'NPS Purificador BTP' in df.columns:
             df['NPS Purificador BTP'] = pd.to_numeric(df['NPS Purificador BTP'], errors='coerce')
             df['Classificacao'] = df['NPS Purificador BTP'].apply(classificar_nps)
        else:
             df['Classificacao'] = None

        # Mesma unificação da base geral, para os dois arquivos casarem.
        if 'Franquia' in df.columns:
            df['Franquia Original'] = df['Franquia']
            df['Franquia'] = unificar_serie(df['Franquia'])

        return df
    except Exception as e:
        st.error(f"Erro ao ler {file_path}: {e}")
        return None

def filtrar_por_programa(df, coluna_programa, selecao):
    if selecao == "Geral": return df
    if coluna_programa not in df.columns: return pd.DataFrame()
    if selecao == "Instalação":
        return df[df[coluna_programa].astype(str).str.contains("Instala", na=False, case=False)]
    return df[df[coluna_programa] == selecao]

ORDEM_PROGRAMAS = ['Pós OS', 'Maintenance', 'Reparo', 'Instalação']

def listar_programas(df):
    if 'Programa de Pesquisa' not in df.columns:
        return []
    presentes = [p for p in df['Programa de Pesquisa'].dropna().unique()]
    ordenados = [p for p in ORDEM_PROGRAMAS if p in presentes]
    ordenados += [p for p in sorted(presentes) if p not in ORDEM_PROGRAMAS]
    return ordenados

# --- KPI CARD (Premium) COM SUPORTE A CLASSE EXTRA ---
def criar_card_kpi(titulo, valor, sub_valor=None, destaque=False, top_bar=False, extra_class=""):
    classe = "kpi-card"
    if destaque:
        classe += " kpi-dark"
    if extra_class:
        classe += f" {extra_class}"
        
    barra = '<div class="kpi-topbar"></div>' if (top_bar and not destaque) else ''
    sub_html = f'<p class="kpi-sub">{sub_valor}</p>' if sub_valor else ''
    
    html_card = (
        f'<div class="{classe}">{barra}'
        f'<p class="kpi-title">{titulo}</p>'
        f'<p class="kpi-value">{valor}</p>'
        f'{sub_html}</div>'
    )
    return st.markdown(html_card, unsafe_allow_html=True)

# --- COMPOSIÇÃO NPS (Promotores / Neutros / Detratores) ---
# Cores sólidas, não os pastéis do gráfico: aqui elas são acento de leitura,
# não preenchimento de área.
CORES_CATEGORIA = {
    'Promotor': '#0E9F6E',
    'Neutro':   '#D9A407',
    'Detrator': '#E02424',
}
# Plural explícito: 'Detrator' + 's' daria "Detrators".
PLURAL_CATEGORIA = {
    'Promotor': 'Promotores',
    'Neutro':   'Neutros',
    'Detrator': 'Detratores',
}
ORDEM_CATEGORIAS = ['Promotor', 'Neutro', 'Detrator']


def _rotulo_mes(valor):
    """'2025-03' -> 'Mar/25'. Mantém o valor original se não for esse formato."""
    try:
        ano, mes = str(valor).split('-')[:2]
        return f"{MAPA_MESES_GLOBAL.get(int(mes), mes)}/{ano[-2:]}"
    except Exception:
        return str(valor)


def _card_categoria(nome, quantidade, participacao):
    """Volume como número principal; a participação vai na linha de apoio,
    onde tem contexto. Juntos na mesma linha, os dois números se confundiam."""
    cor = CORES_CATEGORIA[nome]
    plural = PLURAL_CATEGORIA[nome]
    pct = f"{participacao:.1f}".replace('.', ',')
    largura = f"{max(min(participacao, 100), 0):.1f}"
    return f"""
    <div class="cat-card" style="--cat:{cor};">
        <div class="cat-head"><span class="cat-dot"></span>
            <span class="cat-name">{plural}</span></div>
        <div class="cat-value">{fmt_milhar(quantidade)}</div>
        <div class="cat-sub"><b>{pct}%</b> do total de respostas</div>
        <div class="cat-bar"><i style="width:{largura}%"></i></div>
    </div>"""


def renderizar_composicao_nps(pivot_contagem, pivot_pct, titulo_secao):
    """
    Substitui as três tabelas lado a lado por: cartões de resumo no topo e uma
    única tabela mensal abaixo.

    Antes, cada categoria tinha sua própria tabela com os meses nas colunas, o
    que impedia comparar um mês entre Promotores, Neutros e Detratores e
    espremia tudo em três colunas estreitas. Agora os meses são linhas e as
    categorias, colunas — a leitura horizontal passa a fazer sentido.
    """
    if pivot_contagem.empty:
        return

    presentes = [c for c in ORDEM_CATEGORIAS if c in pivot_contagem.index]
    if not presentes:
        return

    total_geral = float(pivot_contagem.values.sum())

    # --- Camada 1: resumo do período ---
    cards = []
    for nome in ORDEM_CATEGORIAS:
        qtd = float(pivot_contagem.loc[nome].sum()) if nome in pivot_contagem.index else 0.0
        share = (qtd / total_geral * 100) if total_geral else 0.0
        cards.append(_card_categoria(nome, int(qtd), share))
    st.markdown(f'<div class="cat-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    # --- Camada 2: detalhe mês a mês ---
    meses = list(pivot_contagem.columns)
    tabela = {'Mês': [_rotulo_mes(m) for m in meses]}
    for nome in presentes:
        tabela[nome] = [int(v) for v in pivot_contagem.loc[nome].values]
        tabela[f'% {nome}'] = [round(float(v), 1) for v in pivot_pct.loc[nome].values]
    tabela['Total'] = [int(v) for v in pivot_contagem[meses].sum(axis=0).values]

    df_tab = pd.DataFrame(tabela)

    colunas = {
        'Mês': st.column_config.TextColumn('Mês', width='small'),
        'Total': st.column_config.NumberColumn('Total', format='%d', width='small'),
    }
    for nome in presentes:
        plural = PLURAL_CATEGORIA[nome]
        colunas[nome] = st.column_config.NumberColumn(plural, format='%d', width='small')
        colunas[f'% {nome}'] = st.column_config.ProgressColumn(
            f'% {plural}', format='%.1f%%', min_value=0, max_value=100
        )

    st.dataframe(
        df_tab, use_container_width=True, hide_index=True,
        column_config=colunas, column_order=list(df_tab.columns)
    )

    st.download_button(
        label="📥 Baixar composição (.xlsx)",
        data=convert_df_to_excel(df_tab),
        file_name=f"Composicao_NPS_{titulo_secao or 'Geral'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"btn_down_composicao_{titulo_secao}"
    )


# --- FUNÇÃO DE AJUDA PARA TEXTO ---
def gerar_texto_ofensores(df_target):
    if df_target.empty: return "Sem dados."
    
    if 'Classificacao' not in df_target.columns: return "Sem classificação."
    df_probs = df_target[df_target['Classificacao'].isin(['Detrator', 'Neutro'])]
    
    if df_probs.empty: return "Não houveram Detratores/Neutros no período classificado."
    
    txt_saida = ""
    if 'Categorização Primária' in df_probs.columns:
        top_cats = df_probs['Categorização Primária'].value_counts().head(3)
        for cat, qtd in top_cats.items():
            txt_saida += f"- Macro: {cat} ({qtd} casos)\n"
            if 'Subcategorização Primária' in df_probs.columns:
                df_sub = df_probs[df_probs['Categorização Primária'] == cat]
                top_sub = df_sub['Subcategorização Primária'].value_counts().head(2)
                for sub, qtd_sub in top_sub.items():
                    txt_saida += f"   * Detalhe: {sub} ({qtd_sub})\n"
    return txt_saida

def gerar_texto_franquias(df_target):
    if df_target.empty or 'Franquia' not in df_target.columns: return "Sem dados."
    
    df_agg = df_target.groupby('Franquia').apply(
        lambda x: pd.Series({'NPS': calcular_nps_score(x), 'Vol': len(x)})
    ).reset_index()
    df_agg = df_agg[df_agg['Vol'] >= 3]
    
    if df_agg.empty: return "Volume insuficiente por franquia."
    
    melhores = df_agg.nlargest(3, 'NPS')
    piores = df_agg.nsmallest(3, 'NPS')
    
    txt = "TOP 3 (Melhores):\n" + "\n".join([f"- {r['Franquia']}: NPS {r['NPS']:.1f}" for _, r in melhores.iterrows()])
    txt += "\n\nBOTTOM 3 (Atenção):\n" + "\n".join([f"- {r['Franquia']}: NPS {r['NPS']:.1f}" for _, r in piores.iterrows()])
    return txt

# --- Interface Principal ---
if os.path.exists("logo.png"):
    _lc1, _lc2, _lc3 = st.sidebar.columns([1, 2, 1])
    with _lc2:
        st.image("logo.png", use_container_width=True)

st.sidebar.markdown(
    "<h1 style='text-align:center; color:var(--navy); margin:6px 0 0 0;'>NPS</h1>",
    unsafe_allow_html=True
)

data_atualizacao = ler_data_atualizacao()
st.sidebar.markdown(
    f"<p style='text-align:center; color:var(--muted); margin:2px 0 0 0; font-size:12px;'>Atualizado em: {data_atualizacao}</p>",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")

# --- IDENTIFICAÇÃO DO USUÁRIO LOGADO ---
_rotulo_acesso = auth.rotulo_perfil()
st.sidebar.markdown(
    f"<div style='text-align:center; margin-bottom:8px;'>"
    f"<p style='margin:0; font-weight:600; color:var(--navy);'>{st.session_state['usuario_nome']}</p>"
    f"<p style='margin:0; font-size:11px; color:var(--muted);'>{_rotulo_acesso}</p>"
    f"</div>",
    unsafe_allow_html=True
)
_cs1, _cs2 = st.sidebar.columns(2)
with _cs1:
    if st.button("Senha", use_container_width=True, key="btn_senha"):
        auth.modal_alterar_senha()
with _cs2:
    if st.button("Sair", use_container_width=True, key="btn_sair"):
        auth.realizar_logout()
st.sidebar.markdown("---")

df_geral = load_data_geral(ARQUIVO_GERAL)
df_classificado = load_data_classificado(ARQUIVO_CLASSIFICADO)

# ==========================================================================
# RECORTE POR FRANQUIA (CONTROLE DE ACESSO)
# Admin enxerga a base inteira. Usuário comum só enxerga as franquias
# vinculadas ao seu cadastro, por correspondência exata do nome.
# O recorte é aplicado ANTES de qualquer filtro ou cálculo, de modo que
# todos os indicadores já nascem restritos ao escopo do usuário.
# ==========================================================================
FRANQUIAS_BASE = []
if df_geral is not None:
    FRANQUIAS_BASE = sorted(set(df_geral['Franquia'].dropna().astype(str).str.strip()))
    if df_classificado is not None and 'Franquia' in df_classificado.columns:
        FRANQUIAS_BASE = sorted(
            set(FRANQUIAS_BASE) | set(df_classificado['Franquia'].dropna().astype(str).str.strip())
        )

# Cópia da base completa, guardada ANTES do recorte. Serve só para o usuário
# comum comparar o NPS dele com o da companhia — dela sai um único número
# agregado, nunca detalhe de franquia de terceiros.
DF_COMPANHIA = df_geral.copy() if df_geral is not None else None

if not VE_TODAS_FRANQUIAS and df_geral is not None:
    _permitidas = set(st.session_state.get('franquias_permitidas', []))

    if not _permitidas:
        st.error(
            "Seu usuário não possui nenhuma franquia vinculada. "
            "Procure o administrador do painel para liberar seu acesso."
        )
        st.stop()

    df_geral = df_geral[df_geral['Franquia'].astype(str).str.strip().isin(_permitidas)]
    if df_classificado is not None and 'Franquia' in df_classificado.columns:
        df_classificado = df_classificado[
            df_classificado['Franquia'].astype(str).str.strip().isin(_permitidas)
        ]

    if df_geral.empty:
        st.warning(
            "Nenhuma resposta de NPS foi encontrada para as franquias vinculadas ao seu usuário. "
            "Isso ocorre quando o nome da franquia no seu cadastro não coincide exatamente com o "
            "nome usado na base de pesquisa. Procure o administrador do painel."
        )
        st.stop()

if df_geral is not None and df_classificado is not None:

    if 'Num OS' in df_geral.columns and 'Num OS' in df_classificado.columns:
        if 'Segmento' in df_geral.columns and 'Segmento' not in df_classificado.columns:
            temp_seg = df_geral[['Num OS', 'Segmento']].drop_duplicates('Num OS')
            df_classificado = df_classificado.merge(temp_seg, on='Num OS', how='left')
            df_classificado['Segmento'] = df_classificado['Segmento'].fillna('Não Informado')

        if 'Plataforma' in df_geral.columns and 'Plataforma' not in df_classificado.columns:
            temp_plat = df_geral[['Num OS', 'Plataforma']].drop_duplicates('Num OS')
            df_classificado = df_classificado.merge(temp_plat, on='Num OS', how='left')
            df_classificado['Plataforma'] = df_classificado['Plataforma'].fillna('Não Informado')

    plataformas_disp = sorted([str(p) for p in df_geral['Plataforma'].dropna().unique()])
    plataformas_selecionadas = st.sidebar.multiselect(
        "🛰️ Plataforma (Sistema):",
        options=['Todas'] + plataformas_disp,
        default=['Todas'],
        help="Medallia = visão legado | Qualtrics = visão atual. Selecione ambas (ou 'Todas') para a visão consolidada."
    )

    anos_disponiveis = sorted(df_geral['Ano'].dropna().unique().astype(int))
    opcoes_anos = ['Todos'] + [str(a) for a in anos_disponiveis]
    ano_selecionado = st.sidebar.selectbox("Selecione o Ano:", opcoes_anos)
    
    meses_ordem = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    opcoes_meses = ['Todos'] + meses_ordem
    meses_selecionados = st.sidebar.multiselect("Selecione o(s) Mês(es):", options=opcoes_meses, default=['Todos'])

    if 'Segmento' in df_geral.columns:
        segmentos_disp = sorted([str(s) for s in df_geral['Segmento'].dropna().unique()])
        segmentos_selecionados = st.sidebar.multiselect("Selecione o Segmento:", options=['Todos'] + segmentos_disp, default=['Todos'])
    else:
        segmentos_selecionados = ['Todos']

    franquias_geral = set(df_geral['Franquia'].dropna().unique())
    franquias_class = set(df_classificado['Franquia'].dropna().unique()) if 'Franquia' in df_classificado.columns else set()
    todas_franquias = sorted(list(franquias_geral.union(franquias_class)))
    
    usar_todas_franquias = st.sidebar.checkbox("Selecionar Todas as Franquias", value=True)
    if usar_todas_franquias:
        franquias_selecionadas = todas_franquias
    else:
        franquias_selecionadas = st.sidebar.multiselect("Selecione as Franquias:", options=todas_franquias, default=[])

    df_geral_filt = df_geral.copy()
    df_class_filt = df_classificado.copy()

    if "Todas" not in plataformas_selecionadas:
        df_geral_filt = df_geral_filt[df_geral_filt['Plataforma'].isin(plataformas_selecionadas)]
        if 'Plataforma' in df_class_filt.columns:
            df_class_filt = df_class_filt[df_class_filt['Plataforma'].isin(plataformas_selecionadas)]

    if ano_selecionado != 'Todos':
        df_geral_filt = df_geral_filt[df_geral_filt['Ano'] == int(ano_selecionado)]
        if 'Ano' in df_class_filt.columns: df_class_filt = df_class_filt[df_class_filt['Ano'] == int(ano_selecionado)]

    if "Todos" not in meses_selecionados:
        df_geral_filt = df_geral_filt[df_geral_filt['Mes_Nome'].isin(meses_selecionados)]
        if 'Mes_Nome' in df_class_filt.columns: df_class_filt = df_class_filt[df_class_filt['Mes_Nome'].isin(meses_selecionados)]

    if "Todos" not in segmentos_selecionados:
        df_geral_filt = df_geral_filt[df_geral_filt['Segmento'].isin(segmentos_selecionados)]
        if 'Segmento' in df_class_filt.columns: df_class_filt = df_class_filt[df_class_filt['Segmento'].isin(segmentos_selecionados)]

    if franquias_selecionadas:
        df_geral_filt = df_geral_filt[df_geral_filt['Franquia'].isin(franquias_selecionadas)]
        if 'Franquia' in df_class_filt.columns: df_class_filt = df_class_filt[df_class_filt['Franquia'].isin(franquias_selecionadas)]

    # --- NPS DA COMPANHIA (referência para o usuário comum) ---
    # Recebe os MESMOS filtros de período, plataforma e segmento, menos o de
    # franquia. Sem isso a comparação seria injusta: o franqueado veria o mês
    # dele contra a companhia inteira em todo o histórico.
    NPS_COMPANHIA = None
    VOLUME_COMPANHIA = 0
    if not VE_TODAS_FRANQUIAS and DF_COMPANHIA is not None:
        _dfc = DF_COMPANHIA
        if "Todas" not in plataformas_selecionadas:
            _dfc = _dfc[_dfc['Plataforma'].isin(plataformas_selecionadas)]
        if ano_selecionado != 'Todos':
            _dfc = _dfc[_dfc['Ano'] == int(ano_selecionado)]
        if "Todos" not in meses_selecionados:
            _dfc = _dfc[_dfc['Mes_Nome'].isin(meses_selecionados)]
        if "Todos" not in segmentos_selecionados:
            _dfc = _dfc[_dfc['Segmento'].isin(segmentos_selecionados)]
        VOLUME_COMPANHIA = len(_dfc)
        # Piso de amostra: com um recorte muito estreito, a "companhia" poderia
        # se resumir a uma ou duas franquias e o número deixaria de ser
        # referência para virar dado de terceiro.
        if VOLUME_COMPANHIA >= 30:
            NPS_COMPANHIA = calcular_nps_score(_dfc)

    # --- KPIS ---
    st.markdown("### Indicadores de Performance NPS")

    programas_presentes = listar_programas(df_geral_filt)
    val_5s = df_geral_filt['Avaliação do Técnico'].mean() if 'Avaliação do Técnico' in df_geral_filt.columns else None

    # Lógica de Cores para o 5Star
    classe_cor_5star = ""
    if pd.notnull(val_5s):
        if val_5s >= 4.50:
            classe_cor_5star = "kpi-bg-green"
        elif val_5s >= 4.40:
            classe_cor_5star = "kpi-bg-yellow"
        else:
            classe_cor_5star = "kpi-bg-red"

    _nps_usuario = calcular_nps_score(df_geral_filt)

    kpi_specs = [
        {
            "t": "NPS" if not VE_TODAS_FRANQUIAS else "NPS Geral",
            "v": f"{_nps_usuario:.1f}".replace('.', ','),
            "sub": f"Vol. Respostas: {fmt_milhar(len(df_geral_filt))}",
            "dark": True
        }
    ]

    # Referência da companhia, só para quem enxerga um recorte. Para admin e
    # operação o número seria idêntico ao do cartão anterior.
    if not VE_TODAS_FRANQUIAS:
        if NPS_COMPANHIA is not None:
            _delta = _nps_usuario - NPS_COMPANHIA
            # Com pouca resposta o NPS oscila muito: uma franquia com 3
            # respostas promotoras marca 100 e apareceria "31 pontos acima da
            # companhia", o que é ruído vendido como resultado.
            if len(df_geral_filt) < 30:
                _leitura = "amostra pequena para comparar"
                _classe = ""
            elif abs(_delta) < 0.05:
                _leitura = "em linha com a companhia"
                _classe = ""
            elif _delta > 0:
                _leitura = f"você está {_delta:.1f} acima".replace('.', ',')
                _classe = "kpi-bg-green"
            else:
                _leitura = f"você está {abs(_delta):.1f} abaixo".replace('.', ',')
                _classe = "kpi-bg-red"
            kpi_specs.append({
                "t": "NPS Culligan",
                "v": f"{NPS_COMPANHIA:.1f}".replace('.', ','),
                "sub": _leitura,
                "extra_class": _classe,
            })
        else:
            kpi_specs.append({
                "t": "NPS Culligan",
                "v": "-",
                "sub": "amostra insuficiente no filtro atual",
            })
    for prog in programas_presentes:
        df_prog = filtrar_por_programa(df_geral_filt, 'Programa de Pesquisa', prog)
        kpi_specs.append({
            "t": f"NPS {prog}", 
            "v": f"{calcular_nps_score(df_prog):.1f}".replace('.', ','), 
            "sub": f"Vol. Respostas: {fmt_milhar(len(df_prog))}", 
            "top": True
        })
    
    kpi_specs.append({
        "t": "5Star", 
        "v": f"{val_5s:.2f}".replace('.', ',') if pd.notnull(val_5s) else "-", 
        "top": False, 
        "extra_class": classe_cor_5star
    })

    # Renderiza os KPIs
    cols = st.columns(len(kpi_specs))
    for col, spec in zip(cols, kpi_specs):
        with col:
            criar_card_kpi(
                titulo=spec["t"], 
                valor=spec["v"], 
                sub_valor=spec.get("sub"), 
                destaque=spec.get("dark", False), 
                top_bar=spec.get("top", False),
                extra_class=spec.get("extra_class", "")
            )
    st.markdown("---")

    prog_radio_opcoes = ["Geral"] + listar_programas(df_geral)

    _nomes_tabs = ["Visão Geral", "Análise Consolidada", "NPS Franquias Detratores e Neutros",
                   "Classificação NPS", "5Star", "Detalhes", "🧠 Análises Avançadas"]
    if VE_TODAS_FRANQUIAS:
        _nomes_tabs.append("⚙️ Usuários")
    # Disparo de e-mail altera o mundo fora do painel: só administrador.
    if PODE_EDITAR_USUARIOS:
        _nomes_tabs.append("✉️ Comunicação Franquias")

    tabs = st.tabs(_nomes_tabs)
    (tab_visao, tab_consolidada, tab_franquia, tab_kpis, tab_tecnico, tab_detalhes, tab_analises) = tabs[:7]
    tab_admin = tabs[7] if VE_TODAS_FRANQUIAS else None
    tab_comunicacao = tabs[_nomes_tabs.index("✉️ Comunicação Franquias")] if PODE_EDITAR_USUARIOS else None

    # 1. Visão Geral
    with tab_visao:
        def gerar_analise_nps_visual(dataframe, titulo_secao):
            if titulo_secao:
                st.subheader(f"{titulo_secao}")
                
            if dataframe.empty:
                st.info(f"Não há dados para {titulo_secao}.")
                return
            pivot_contagem = dataframe.pivot_table(index='Classificacao', columns='Mes_Ano_Sort', values='NPS Purificador BTP', aggfunc='count', fill_value=0).sort_index(axis=1)
            pivot_pct = pivot_contagem.div(pivot_contagem.sum(axis=0), axis=1) * 100
            
            s_prom = pivot_pct.loc['Promotor'] if 'Promotor' in pivot_pct.index else pd.Series(0, index=pivot_pct.columns)
            s_detr = pivot_pct.loc['Detrator'] if 'Detrator' in pivot_pct.index else pd.Series(0, index=pivot_pct.columns)
            nps_raw = (s_prom - s_detr).fillna(0)
            
            nps_text = [f"{x:.1f}".replace('.', ',') for x in nps_raw.values]

            df_chart = pivot_contagem.reset_index().melt(id_vars='Classificacao', var_name='Mes', value_name='Quantidade')
            
            titulo_grafico = "Evolução Mensal (NPS)" if titulo_secao == "NPS Geral" or titulo_secao == "" else f"Evolução Mensal - {titulo_secao}"
            
            fig = px.bar(df_chart, x='Mes', y='Quantidade', color='Classificacao', title=titulo_grafico, color_discrete_map=CORES_NPS_PASTEL, text_auto=True)
            
            fig.add_trace(go.Scatter(x=nps_raw.index.astype(str), y=[pivot_contagem.sum().max() * 1.1] * len(nps_raw), text=nps_text, mode='text+markers', textposition='top center', name='NPS Score', textfont=dict(size=14, color='black'), marker=dict(size=1, color='rgba(0,0,0,0)')))
            
            vals_x = df_chart['Mes'].unique()
            text_x = []
            for v in vals_x:
                try:
                    mes_num = int(v.split('-')[1])
                    text_x.append(MAPA_MESES_GLOBAL.get(mes_num, v))
                except:
                    text_x.append(v)

            fig.update_layout(
                barmode='stack', yaxis_title="Quantidade", xaxis_title="Mês", 
                yaxis_range=[0, pivot_contagem.sum().max() * 1.25], 
                margin=dict(t=40),
                title_font=dict(size=14),
                xaxis=dict(
                    tickmode='array',
                    tickvals=vals_x,
                    ticktext=text_x
                )
            )
            st.plotly_chart(fundo_transparente(fig), use_container_width=True, theme=None)

            renderizar_composicao_nps(pivot_contagem, pivot_pct, titulo_secao)
            st.markdown("---")

        gerar_analise_nps_visual(df_geral_filt, "")

        if 'Programa de Pesquisa' in df_geral_filt.columns:
            for prog in listar_programas(df_geral_filt):
                df_prog = filtrar_por_programa(df_geral_filt, 'Programa de Pesquisa', prog)
                gerar_analise_nps_visual(df_prog, prog)

    # 2. Análise Consolidada
    with tab_consolidada:
        st.subheader("📑 Visão Executiva Consolidada")
        st.info("""
        **Como ler o Mapa de Calor:** Este gráfico exibe a **concentração de casos** por categoria e mês.  
        As cores mais escuras (azul forte) indicam **maior volume de ocorrências**, facilitando a identificação imediata dos principais ofensores e padrões de sazonalidade.
        """)
        tipo_pes = st.radio("Programa:", prog_radio_opcoes, horizontal=True, key="rd_cons")
        df_cons = filtrar_por_programa(df_class_filt, 'Programa de Pesquisa', tipo_pes)
        if not df_cons.empty and 'Categorização Primária' in df_cons.columns:
            meses_p = sorted(df_cons['Mes_Num'].unique())
            mapa_i = {1:'Jan', 2:'Fev', 3:'Mar', 4:'Abr', 5:'Mai', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Set', 10:'Out', 11:'Nov', 12:'Dez'}
            cols_ord = [mapa_i[m] for m in meses_p if m in mapa_i]
            piv_res = df_cons.pivot_table(index='Categorização Primária', columns='Mes_Nome', values='ID', aggfunc='count', fill_value=0).reindex(columns=cols_ord, fill_value=0)
            piv_res['Total'] = piv_res.sum(axis=1)
            piv_heat = piv_res.sort_values('Total', ascending=False).drop(columns=['Total'])
            
            fig = px.imshow(piv_heat, labels=dict(x="Mês", y="Categoria", color="Qtd"), color_continuous_scale='Blues', text_auto=True, aspect="auto", title="Mapa de Calor: Categoria x Mês")
            fig.update_layout(title_font=dict(size=14))
            st.plotly_chart(fundo_transparente(fig), use_container_width=True, theme=None)
            st.markdown("---")
            st.markdown("### 📋 Top 5 Ofensores")
            for cat in piv_heat.index:
                with st.expander(f"📂 {cat}", expanded=False):
                    df_c = df_cons[df_cons['Categorização Primária'] == cat]
                    piv_s = df_c.pivot_table(index='Subcategorização Primária', columns='Mes_Nome', values='ID', aggfunc='count', fill_value=0).reindex(columns=cols_ord, fill_value=0)
                    piv_s['Total'] = piv_s.sum(axis=1)
                    
                    df_top5 = piv_s.nlargest(5, 'Total').drop(columns=['Total'])
                    st.dataframe(df_top5.style.background_gradient(cmap='Blues', axis=None).format("{:.0f}"), use_container_width=True)
                    
                    excel_data = convert_df_to_excel(df_top5)
                    st.download_button(
                        label=f"📥 Baixar {cat} (.xlsx)",
                        data=excel_data,
                        file_name=f"Top5_{cat}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"btn_down_{cat}"
                    )
        else: st.warning("Sem dados.")

    # 3. Franquias
    with tab_franquia:
        st.subheader("Análise Detalhada por Franquia")
        tp_frq = st.radio("Programa:", prog_radio_opcoes, horizontal=True, key="rd_frq")
        df_fr = filtrar_por_programa(df_class_filt, 'Programa de Pesquisa', tp_frq)
        if not df_fr.empty and 'Franquia' in df_fr.columns:
            frqs = sorted(df_fr['Franquia'].dropna().unique())
            sel_fr = st.multiselect("Franquias (Visão Local):", ['Todas']+frqs, default=['Todas'])
            df_fin = df_fr if "Todas" in sel_fr else df_fr[df_fr['Franquia'].isin(sel_fr)]
            
            if not df_fin.empty and 'Subcategorização Primária' in df_fin.columns:
                c1, c2 = st.columns([3, 4])
                df_t = df_fin['Subcategorização Primária'].value_counts().reset_index()
                df_t.columns = ['Motivo', 'Quantidade']
                df_t['%'] = (df_t['Quantidade']/df_t['Quantidade'].sum()*100).map('{:.1f}%'.format)
                
                with c1:
                    st.dataframe(df_t, use_container_width=True, hide_index=True)
                    excel_data_t = convert_df_to_excel(df_t)
                    st.download_button(
                        label="📥 Baixar Resumo (.xlsx)",
                        data=excel_data_t,
                        file_name="Resumo_Franquias.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_down_frq_resumo"
                    )
                
                with c2:
                    df_g = df_t.copy()
                    if len(df_g)>5: df_g = pd.concat([df_g.iloc[:5], pd.DataFrame({'Motivo':['Outros'], 'Quantidade':[df_g.iloc[5:]['Quantidade'].sum()]})])
                    
                    fig = go.Figure(data=[go.Pie(
                        labels=df_g['Motivo'], 
                        values=df_g['Quantidade'], 
                        hole=0.5, 
                        marker=dict(colors=CORES_BLUES), 
                        showlegend=False,
                        textinfo='label+percent',
                        textposition='outside'
                    )])
                    fig.update_layout(margin=dict(t=40, b=20, l=120, r=120), title_text="Distribuição por Motivo", title_font=dict(size=14))
                    st.plotly_chart(fundo_transparente(fig), use_container_width=True, theme=None)
                
                st.markdown("---")
                st.markdown("#### 📊 Volume por Franquia (Absoluto e %)")
                
                df_vol_franquia = df_fin['Franquia'].value_counts().reset_index()
                df_vol_franquia.columns = ['Franquia', 'Volume Absoluto']
                tot_vol_franquia = df_vol_franquia['Volume Absoluto'].sum()
                df_vol_franquia['%'] = (df_vol_franquia['Volume Absoluto'] / tot_vol_franquia * 100).map('{:.1f}%'.format)
                
                st.dataframe(df_vol_franquia, use_container_width=True, hide_index=True)
                
                excel_data_vol_fr = convert_df_to_excel(df_vol_franquia)
                st.download_button(
                    label="📥 Baixar Volumes por Franquia (.xlsx)",
                    data=excel_data_vol_fr,
                    file_name="Volume_Franquias_Detratores_Neutros.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_down_frq_vol"
                )

                if 'Num OS' in df_fin.columns and 'Num OS' in df_geral.columns:
                    cols_source = ['Num OS', 'Comentário NPS Ecohouse', 'Franquia', 'Nome do Técnico', 'Segmento']
                    cols_source = [c for c in cols_source if c in df_geral.columns]
                    
                    temp_geral_info = df_geral[cols_source].drop_duplicates('Num OS')
                    df_fin = df_fin.merge(temp_geral_info, on='Num OS', how='left', suffixes=('', '_geral'))
                    
                    if 'Franquia_geral' in df_fin.columns: df_fin['Franquia'] = df_fin['Franquia'].fillna(df_fin['Franquia_geral'])
                    if 'Nome do Técnico_geral' in df_fin.columns: df_fin['Nome do Técnico'] = df_fin['Nome do Técnico_geral']
                    if 'Segmento_geral' in df_fin.columns: df_fin['Segmento'] = df_fin['Segmento'].fillna(df_fin['Segmento_geral'])
                    if 'Comentário NPS Ecohouse_geral' in df_fin.columns: df_fin['Comentário NPS Ecohouse'] = df_fin['Comentário NPS Ecohouse'].fillna(df_fin['Comentário NPS Ecohouse_geral'])

                st.markdown("---")
                st.markdown("#### 📄 Extrato Detalhado")
                cols_ver = ['Data', 'Num OS', 'Franquia', 'Segmento', 'Nome do Técnico', 'Categorização Primária', 'Subcategorização Primária', 'Comentário NPS Ecohouse']
                cols_fin = [c for c in cols_ver if c in df_fin.columns]
                
                df_extract = df_fin[cols_fin].sort_values('Data', ascending=False)
                st.dataframe(df_extract, use_container_width=True, hide_index=True)
                
                excel_data_ext = convert_df_to_excel(df_extract)
                st.download_button(
                    label="📥 Baixar Extrato Detalhado (.xlsx)",
                    data=excel_data_ext,
                    file_name="Extrato_Franquias.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_down_frq_extract"
                )

            else: st.warning("Sem dados.")
        else: st.warning("Sem dados.")

    # 4. Classificação NPS
    with tab_kpis:
        st.subheader("Classificação NPS")
        tp_kp = st.radio("Visão:", prog_radio_opcoes, horizontal=True, key="rd_kp")
        df_kp = filtrar_por_programa(df_class_filt, 'Programa de Pesquisa', tp_kp)
        
        if not df_kp.empty:
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.markdown("**Resumo por Categoria**")
                res = df_kp.groupby(['Categorização Primária', 'Subcategorização Primária']).size().reset_index(name='Qtd').sort_values('Qtd', ascending=False)
                res['%'] = (res['Qtd']/res['Qtd'].sum()*100).map('{:.1f}%'.format)
                st.dataframe(res, use_container_width=True, hide_index=True)
                
                excel_data_res = convert_df_to_excel(res)
                st.download_button(
                    label="📥 Baixar Resumo (.xlsx)",
                    data=excel_data_res,
                    file_name="Resumo_Classificacao.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_down_class_resumo"
                )
            
            with c2:
                if 'Categorização Primária' in df_kp.columns:
                    piz = df_kp['Categorização Primária'].value_counts().reset_index()
                    piz.columns = ['Cat', 'Qtd']
                    if len(piz)>6: piz = pd.concat([piz.iloc[:6], pd.DataFrame({'Cat':['Outros'], 'Qtd':[piz.iloc[6:]['Qtd'].sum()]})])
                    
                    fig = go.Figure(data=[go.Pie(
                        labels=piz['Cat'], 
                        values=piz['Qtd'], 
                        hole=.5, 
                        marker=dict(colors=CORES_BLUES), 
                        showlegend=False,
                        textinfo='label+percent',
                        textposition='outside'
                    )])
                    fig.update_layout(
                        title_text="Distribuição Macro", 
                        margin=dict(t=40, b=20, l=60, r=60), 
                        height=350,
                        title_font=dict(size=14)
                    )
                    st.plotly_chart(fundo_transparente(fig), use_container_width=True, theme=None)

            st.divider()
            st.subheader("🔎 Filtro de Detalhamento e Extrato")
            
            if 'Categorização Primária' in df_kp.columns:
                opcoes_cat = sorted(df_kp['Categorização Primária'].astype(str).unique())
                sel_cat_prim = st.multiselect("Selecione a Categoria Primária:", opcoes_cat)
                
                if sel_cat_prim:
                    df_filtered = df_kp[df_kp['Categorização Primária'].isin(sel_cat_prim)]
                else:
                    df_filtered = df_kp 
                
                if 'Subcategorização Primária' in df_filtered.columns:
                    opcoes_sub = sorted(df_filtered['Subcategorização Primária'].astype(str).unique())
                    sel_cat_sec = st.multiselect("Selecione a Subcategoria:", opcoes_sub)
                    
                    if sel_cat_sec:
                        df_final_extrato = df_filtered[df_filtered['Subcategorização Primária'].isin(sel_cat_sec)]
                    else:
                        df_final_extrato = df_filtered
                else:
                    df_final_extrato = df_filtered

                st.markdown("#### 📄 Extrato da Seleção")
                
                if 'Num OS' in df_final_extrato.columns and 'Num OS' in df_geral.columns:
                    cols_extra = ['Num OS', 'Comentário NPS Ecohouse', 'Franquia', 'Nome do Técnico', 'Segmento']
                    cols_extra = [c for c in cols_extra if c in df_geral.columns]
                    
                    temp_data = df_geral[cols_extra].drop_duplicates('Num OS')
                    df_final_extrato = df_final_extrato.merge(temp_data, on='Num OS', how='left', suffixes=('', '_geral'))
                    
                    if 'Franquia_geral' in df_final_extrato.columns: df_final_extrato['Franquia'] = df_final_extrato['Franquia'].fillna(df_final_extrato['Franquia_geral'])
                    if 'Nome do Técnico_geral' in df_final_extrato.columns: df_final_extrato['Nome do Técnico'] = df_final_extrato['Nome do Técnico_geral']
                    if 'Segmento_geral' in df_final_extrato.columns: df_final_extrato['Segmento'] = df_final_extrato['Segmento'].fillna(df_final_extrato['Segmento_geral'])
                    if 'Comentário NPS Ecohouse_geral' in df_final_extrato.columns: df_final_extrato['Comentário NPS Ecohouse'] = df_final_extrato['Comentário NPS Ecohouse'].fillna(df_final_extrato['Comentário NPS Ecohouse_geral'])

                cols_display = ['Data', 'Num OS', 'Franquia', 'Segmento', 'Nome do Técnico', 'Categorização Primária', 'Subcategorização Primária', 'Comentário NPS Ecohouse']
                cols_present = [c for c in cols_display if c in df_final_extrato.columns]
                
                df_display = df_final_extrato[cols_present].sort_values('Data', ascending=False)
                st.dataframe(df_display, use_container_width=True, hide_index=True)
                
                excel_data_display = convert_df_to_excel(df_display)
                st.download_button(
                    label="📥 Baixar Extrato Filtrado (.xlsx)",
                    data=excel_data_display,
                    file_name="Extrato_Classificacao_Filtrado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_down_class_filtered"
                )

        else: st.warning("Sem dados classificados para os filtros globais.")

    # 5. 5Star
    with tab_tecnico:
        st.subheader("⭐ Programa 5Star")
        cr, cf, cm = st.columns([1.2, 1, 1]) 
        
        tp_tec = cr.radio("Programa:", prog_radio_opcoes, horizontal=True, key="rd_tec")
        ops = ['Todas'] + sorted(df_geral_filt['Franquia'].unique())
        sel_loc = cf.multiselect("Franquias:", ops, default=['Todas'])
        
        df_tc = filtrar_por_programa(df_geral_filt, 'Programa de Pesquisa', tp_tec)
        if "Todas" not in sel_loc: df_tc = df_tc[df_tc['Franquia'].isin(sel_loc)]
        
        if not df_tc.empty and 'Avaliação do Técnico' in df_tc.columns:
            media_val = df_tc['Avaliação do Técnico'].mean()
            
            classe_aba_5star = ""
            if pd.notnull(media_val):
                if media_val >= 4.50:
                    classe_aba_5star = "kpi-bg-green"
                elif media_val >= 4.40:
                    classe_aba_5star = "kpi-bg-yellow"
                else:
                    classe_aba_5star = "kpi-bg-red"

            with cm:
                criar_card_kpi("Média Geral", f"{media_val:.2f}", extra_class=classe_aba_5star)
            
            df_evol = df_tc.groupby('Mes_Ano_Sort')['Avaliação do Técnico'].mean().reset_index()
            fig = px.bar(df_evol, x='Mes_Ano_Sort', y='Avaliação do Técnico', title="Evolução Mensal da Nota", text_auto='.2f', color_discrete_sequence=['#08306b'])
            
            vals_x_tc = df_evol['Mes_Ano_Sort'].unique()
            text_x_tc = []
            for v in vals_x_tc:
                try:
                    mes_num = int(v.split('-')[1])
                    text_x_tc.append(MAPA_MESES_GLOBAL.get(mes_num, v))
                except:
                    text_x_tc.append(v)
            
            fig.update_yaxes(range=[0, 5.5])
            fig.update_layout(
                title_font=dict(size=14), 
                margin=dict(t=40),
                xaxis=dict(
                    tickmode='array',
                    tickvals=vals_x_tc,
                    ticktext=text_x_tc
                )
            )
            st.plotly_chart(fundo_transparente(fig), use_container_width=True, theme=None)
            
            st.markdown("---")
            sel_t = st.selectbox("Técnico:", ['Todos'] + sorted(df_tc['Nome do Técnico'].dropna().astype(str).unique()))
            
            df_tf = df_tc if sel_t == 'Todos' else df_tc[df_tc['Nome do Técnico'] == sel_t]
            
            ind = df_tf.groupby(['Nome do Técnico', 'Franquia']).agg(Media=('Avaliação do Técnico', 'mean'), Qtd=('Avaliação do Técnico', 'count')).reset_index()
            
            df_rank = ind[ind['Qtd']>0].sort_values('Media', ascending=False)
            st.dataframe(df_rank.style.format({'Media':'{:.2f}'}).background_gradient(subset=['Media'], cmap='RdYlGn', vmin=1, vmax=5), use_container_width=True)
            
            excel_data_rank = convert_df_to_excel(df_rank)
            st.download_button(
                label="📥 Baixar Ranking (.xlsx)",
                data=excel_data_rank,
                file_name="Ranking_Tecnicos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_down_rank"
            )

            df_det_tec = df_tf[['Data da resposta local', 'Nome do Técnico', 'Avaliação do Técnico', 'Num OS', 'Franquia']].sort_values('Data da resposta local', ascending=False)
            st.dataframe(df_det_tec, use_container_width=True, hide_index=True)
            
            excel_data_det_tec = convert_df_to_excel(df_det_tec)
            st.download_button(
                label="📥 Baixar Extrato de Notas (.xlsx)",
                data=excel_data_det_tec,
                file_name="Extrato_Notas_Tecnicos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_down_det_tec"
            )

        else: st.warning("Sem dados.")

    # 6. Detalhes
    with tab_detalhes:
        st.subheader("🔍 Detalhamento OS")
        os_in = st.text_input("Número da OS:")
        if os_in:
            clean = os_in.strip().replace('.0', '')
            rg = df_geral[df_geral['Num OS'] == clean]
            rc = df_classificado[df_classificado['Num OS'] == clean] if 'Num OS' in df_classificado.columns else pd.DataFrame()
            if rg.empty and rc.empty: st.error("Não encontrado.")
            else:
                if not rg.empty:
                    st.dataframe(rg, use_container_width=True, hide_index=True)
                    excel_data_rg = convert_df_to_excel(rg)
                    st.download_button(
                        label="📥 Baixar Dados Gerais (.xlsx)",
                        data=excel_data_rg,
                        file_name=f"OS_{clean}_Geral.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_down_os_geral"
                    )

                    if 'Comentário NPS Ecohouse' in rg.columns: st.info(f"Comentário: {rg.iloc[0]['Comentário NPS Ecohouse']}")
                if not rc.empty:
                    st.markdown(f"**Classificação:** `{rc.iloc[0].get('Categorização Primária','-')}` > `{rc.iloc[0].get('Subcategorização Primária','-')}`")
                    st.dataframe(rc, use_container_width=True, hide_index=True)
                    excel_data_rc = convert_df_to_excel(rc)
                    st.download_button(
                        label="📥 Baixar Classificação (.xlsx)",
                        data=excel_data_rc,
                        file_name=f"OS_{clean}_Classificado.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_down_os_class"
                    )

    # 7. Análises Avançadas
    # Dupla trava: precisa ser admin E digitar a senha da seção.
    SENHA_ANALISES = "1010"

    with tab_analises:
        st.subheader("🧠 Command Center Estratégico & Insights")

        senha = None
        if not VE_TODAS_FRANQUIAS:
            st.info("Esta seção é restrita a usuários administradores e de operação.")
        else:
            senha = st.text_input("🔒 Senha de Acesso:", type="password", key="senha_analises")

        if VE_TODAS_FRANQUIAS and senha == SENHA_ANALISES:
            modo_analise = st.radio(
                "Selecione o Modo de Análise:",
                ["📊 Fechamento do Período (Atual)", "⚔️ Comparativo Estratégico (A vs B)"],
                horizontal=True
            )
            st.markdown("---")

            if modo_analise == "📊 Fechamento do Período (Atual)":
                st.markdown("Gera um relatório completo sobre o período selecionado nos filtros laterais.")
                
                if 'Classificacao' not in df_class_filt.columns or df_class_filt['Classificacao'].isnull().all():
                     if 'Num OS' in df_class_filt.columns and 'Num OS' in df_geral_filt.columns:
                         temp_class = df_geral_filt[['Num OS', 'Classificacao']].drop_duplicates('Num OS')
                         df_class_filt = df_class_filt.merge(temp_class, on='Num OS', how='left', suffixes=('', '_y'))
                         if 'Classificacao_y' in df_class_filt.columns:
                             df_class_filt['Classificacao'] = df_class_filt['Classificacao'].fillna(df_class_filt['Classificacao_y'])

                txt_programas = ""
                marcadores = ['🅰️', '🅱️', '🅲️', '🅳️', '🅴️']
                for idx, prog in enumerate(listar_programas(df_geral_filt)):
                    marc = marcadores[idx] if idx < len(marcadores) else '▶️'
                    df_prog = filtrar_por_programa(df_geral_filt, 'Programa de Pesquisa', prog)
                    df_class_prog = filtrar_por_programa(df_class_filt, 'Programa de Pesquisa', prog)
                    txt_programas += f"{marc} {prog}\n"
                    txt_programas += f"- NPS: {calcular_nps_score(df_prog):.1f} (Vol: {len(df_prog)})\n"
                    txt_programas += "- Principais Ofensores (Categorias > Subcategorias):\n"
                    txt_programas += f"{gerar_texto_ofensores(df_class_prog)}\n"
                    txt_programas += "- Performance de Franquias:\n"
                    txt_programas += f"{gerar_texto_franquias(df_prog)}\n\n"

                txt_comentarios = "Sem comentários disponíveis."
                if 'Comentário NPS Ecohouse' in df_geral_filt.columns:
                    df_coments_det = df_geral_filt[
                        (df_geral_filt['Classificacao'] == 'Detrator') & 
                        (df_geral_filt['Comentário NPS Ecohouse'].notna()) & 
                        (df_geral_filt['Comentário NPS Ecohouse'] != '-')
                    ]
                    df_coments_prom = df_geral_filt[
                        (df_geral_filt['Classificacao'] == 'Promotor') & 
                        (df_geral_filt['Comentário NPS Ecohouse'].notna())
                    ]
                    
                    if not df_coments_det.empty:
                        sample_det = df_coments_det['Comentário NPS Ecohouse'].sample(min(len(df_coments_det), 3)).tolist()
                    else: sample_det = []
                    
                    if not df_coments_prom.empty:
                        sample_prom = df_coments_prom['Comentário NPS Ecohouse'].sample(min(len(df_coments_prom), 3)).tolist()
                    else: sample_prom = []
                    
                    if sample_det or sample_prom:
                        txt_comentarios = "💬 O que os Detratores estão dizendo (Amostra):\n" + "\n".join([f'- "{c}"' for c in sample_det])
                        txt_comentarios += "\n\n💬 O que os Promotores elogiam (Amostra):\n" + "\n".join([f'- "{c}"' for c in sample_prom])

                txt_pareto = "Dados insuficientes."
                if 'Avaliação do Técnico' in df_geral_filt.columns:
                    df_bad_tec = df_geral_filt[df_geral_filt['Avaliação do Técnico'] < 4]
                    total_tecnicos_ativos = df_geral_filt['Nome do Técnico'].nunique()
                    tecnicos_com_erro = df_bad_tec['Nome do Técnico'].nunique()
                    
                    if total_tecnicos_ativos > 0:
                        pct_impacto = (tecnicos_com_erro / total_tecnicos_ativos) * 100
                        txt_pareto = f"De {total_tecnicos_ativos} técnicos ativos no período, {tecnicos_com_erro} ({pct_impacto:.1f}%) receberam pelo menos uma avaliação negativa (<4)."
                        if pct_impacto < 20:
                            txt_pareto += " -> Problema CONCENTRADO em poucos indivíduos (Ação: Treinamento/Reciclagem pontual)."
                        else:
                            txt_pareto += " -> Problema SISTÊMICO espalhado na equipe (Ação: Revisão de Processo Global)."

                prompt_text = f"""
Atue como Head de Customer Experience. Analise os dados do dashboard (Filtros: {anos_disponiveis if ano_selecionado == 'Todos' else ano_selecionado} - {meses_selecionados} - Seg: {segmentos_selecionados} - Plataforma: {plataformas_selecionadas}).

1. CONTEXTO GERAL
- Volume Total: {len(df_geral_filt)}
- NPS Global: {calcular_nps_score(df_geral_filt):.1f}

2. ANÁLISE QUALITATIVA (VOZ DO CLIENTE)
{txt_comentarios}

3. ANÁLISE DE EQUIPE (PARETO)
{txt_pareto}

4. DETALHAMENTO POR PROGRAMA
{txt_programas}
5. PROGRAMA TÉCNICO (5STAR)
- Nota Média Geral: {df_geral_filt['Avaliação do Técnico'].mean():.2f}/5.0
- Técnicos em Alerta (Nota < 4.5 e Vol > 3): 
{", ".join([f"{row['Nome do Técnico']} ({row['Avaliação do Técnico']:.1f})" for i, row in df_geral_filt[df_geral_filt['Avaliação do Técnico'] < 4.5].groupby('Nome do Técnico')['Avaliação do Técnico'].mean().reset_index().head(5).iterrows()])}

---
TAREFA:
Crie um relatório estratégico contendo:
1. **Análise de Sentimento:** Baseado nos comentários, qual é o tom emocional do cliente?
2. **Diagnóstico Operacional:** O problema é gente (Pareto) ou processo (Ofensores)?
3. **Plano de Ação:** 3 ações mandatórias para o próximo mês.
"""
                st.info("👇 Copie para IA (Gera Fechamento):")
                st.code(prompt_text, language="text")

            else:
                st.subheader("Selecione os Períodos para Comparação")
                c_a, c_b = st.columns(2)
                if 'Mes_Ano_Sort' in df_geral.columns:
                    periodos_disp = sorted(df_geral['Mes_Ano_Sort'].unique())
                else: periodos_disp = []

                with c_a: 
                    per_a = st.selectbox("📅 Período A (Base):", periodos_disp, index=len(periodos_disp)-2 if len(periodos_disp)>1 else 0)
                with c_b:
                    per_b = st.selectbox("📅 Período B (Atual/Comp):", periodos_disp, index=len(periodos_disp)-1 if len(periodos_disp)>0 else 0)

                if st.button("Gerar Comparativo Estratégico"):
                    df_a_geral = df_geral[df_geral['Mes_Ano_Sort'] == per_a]
                    df_b_geral = df_geral[df_geral['Mes_Ano_Sort'] == per_b]
                    
                    df_class_total = load_data_classificado(ARQUIVO_CLASSIFICADO)
                    if 'Num OS' in df_class_total.columns and 'Num OS' in df_geral.columns:
                         temp_cls = df_geral[['Num OS', 'Classificacao']].drop_duplicates('Num OS')
                         df_class_total = df_class_total.merge(temp_cls, on='Num OS', how='left', suffixes=('', '_y'))
                         if 'Classificacao_y' in df_class_total.columns:
                             df_class_total['Classificacao'] = df_class_total['Classificacao'].fillna(df_class_total['Classificacao_y'])
                    
                    df_a_class = df_class_total[df_class_total['Mes_Ano_Sort'] == per_a]
                    df_b_class = df_class_total[df_class_total['Mes_Ano_Sort'] == per_b]

                    nps_a, nps_b = calcular_nps_score(df_a_geral), calcular_nps_score(df_b_geral)
                    vol_a, vol_b = len(df_a_geral), len(df_b_geral)
                    tec_a, tec_b = df_a_geral['Avaliação do Técnico'].mean(), df_b_geral['Avaliação do Técnico'].mean()

                    delta_nps = nps_b - nps_a
                    delta_vol = vol_b - vol_a

                    progs_comp = listar_programas(pd.concat([df_a_geral, df_b_geral], ignore_index=True))
                    txt_prog_comp = ""
                    for prog in progs_comp:
                        a_p = filtrar_por_programa(df_a_geral, 'Programa de Pesquisa', prog)
                        b_p = filtrar_por_programa(df_b_geral, 'Programa de Pesquisa', prog)
                        txt_prog_comp += f"- {prog}: {calcular_nps_score(a_p):.1f} -> {calcular_nps_score(b_p):.1f}\n"

                    prompt_comp = f"""
Atue como Head de Estratégia CX. Realize uma análise comparativa (Year-over-Year ou Month-over-Month) entre dois períodos.

PERÍODO A ({per_a})  vs  PERÍODO B ({per_b})

1. KPIs MACRO
- NPS: {nps_a:.1f}  ➡️  {nps_b:.1f} (Delta: {delta_nps:+.1f})
- Volume: {vol_a}  ➡️  {vol_b} (Delta: {delta_vol:+})
- Nota Técnica: {tec_a:.2f} ➡️ {tec_b:.2f}

2. EVOLUÇÃO DOS OFENSORES (O problema mudou?)
[Período A - Detalhes]
{gerar_texto_ofensores(df_a_class)}

[Período B - Detalhes]
{gerar_texto_ofensores(df_b_class)}

3. DETALHE POR PROGRAMA (NPS A -> NPS B)
{txt_prog_comp}
---
TAREFA ANALÍTICA:
1. **Veredito da Evolução:** O NPS subiu ou caiu? Quais programas puxaram o resultado?
2. **Análise de Causa Raiz:** O principal ofensor do Período A foi resolvido no B? Surgiu um novo ofensor crítico?
3. **Recomendação Tática:** O que a diretoria deve fazer para manter a tendência de alta ou reverter a queda no próximo ciclo?
"""
                    st.info("👇 Copie para IA (Gera Comparativo):")
                    st.code(prompt_comp, language="text")

        elif VE_TODAS_FRANQUIAS and senha:
            st.error("Senha incorreta.")

    # 8. Administração de Usuários (admin edita, operação consulta)
    if VE_TODAS_FRANQUIAS and tab_admin is not None:
        with tab_admin:
            render_admin_usuarios(FRANQUIAS_BASE, somente_leitura=not PODE_EDITAR_USUARIOS)

    # 9. Comunicação Franquias (somente admin)
    # Recebe df_geral SEM os filtros do menu lateral: o e-mail tem período
    # próprio (mês de referência vs mês anterior) e não deve variar conforme
    # o que estiver filtrado na tela no momento do disparo.
    if PODE_EDITAR_USUARIOS and tab_comunicacao is not None:
        with tab_comunicacao:
            render_comunicacao(df_geral, df_classificado)

else:
    st.error(f"Arquivos {ARQUIVO_GERAL} e {ARQUIVO_CLASSIFICADO} não encontrados.")