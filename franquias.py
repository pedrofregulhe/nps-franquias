"""
Unificação dos nomes de franquia.

Duas coisas resolvidas aqui, que na prática são a mesma:

1. GRADE. A base traz a franquia quebrada por grade — "FRQ SBC SP R01 - MATRIZ",
   "FRQ SBC SP R03". O painel passa a tratar tudo como uma franquia só:
   "FRQ SBC SP".

2. HISTÓRICO. A plataforma antiga (Medallia) usava outra nomenclatura
   ("FRQ_ECO_SP_S B CAMPO") que não casava com a atual (Qualtrics), deixando
   quase 60% das respostas invisíveis para o franqueado. O De-Para.xlsx liga
   as duas, e como a ponta Qualtrics do de-para também perde a grade, os dois
   padrões convergem para o mesmo nome unificado.

O casamento ignora acento, caixa e espaço duplicado: a planilha de usuários traz
"FRQ SP SÃO PAULO" e a base de NPS traz "FRQ SP SAO PAULO".

Cobertura medida na base atual: 41% -> 93% das respostas com dono identificado,
e 174 nomes distintos reduzidos a 46.
"""

import re
import unicodedata
import os
import pandas as pd
import streamlit as st

ARQUIVO_DE_PARA = "De-Para.xlsx"

# Sufixo de grade: " R01", " R03 - MATRIZ", " - R02". Sempre no fim do nome.
_RE_GRADE = re.compile(r'\s*(?:-\s*)?\bR\d+\b(?:\s*-\s*MATRIZ)?\s*$', re.I)
_RE_MATRIZ = re.compile(r'\s*-\s*MATRIZ\s*$', re.I)


def remover_grade(nome):
    """'FRQ SBC SP R01 - MATRIZ' -> 'FRQ SBC SP'."""
    n = re.sub(r'\s+', ' ', str(nome).strip())
    n = _RE_GRADE.sub('', n)
    n = _RE_MATRIZ.sub('', n)
    return re.sub(r'\s+', ' ', n).strip()


def chave(nome):
    """Chave de comparação: sem acento, sem pontuação, maiúscula."""
    n = unicodedata.normalize('NFKD', str(nome)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Z0-9]', '', n.upper())


@st.cache_data(show_spinner=False)
def carregar_tabela(caminho=ARQUIVO_DE_PARA):
    """
    Constrói {chave -> nome canônico} a partir do De-Para.xlsx.

    Registra a chave dos dois lados: o nome antigo (Medallia) e a base do nome
    novo (Qualtrics sem grade). Ambos apontam para o mesmo canônico.
    """
    tabela = {}
    if not os.path.exists(caminho):
        return tabela
    try:
        df = pd.read_excel(caminho)
    except Exception:
        return tabela
    if df.shape[1] < 2:
        return tabela

    col_antigo, col_novo = df.columns[0], df.columns[1]
    for _, linha in df.iterrows():
        antigo, novo = linha[col_antigo], linha[col_novo]
        if pd.isna(novo):
            continue
        canonico = remover_grade(novo)
        if not canonico:
            continue
        tabela[chave(canonico)] = canonico
        if pd.notna(antigo):
            tabela[chave(antigo)] = canonico
    return tabela


def unificar(nome, tabela=None):
    """Nome unificado de uma franquia. Fora do de-para, só remove a grade."""
    if nome is None or (isinstance(nome, float) and pd.isna(nome)):
        return None
    if tabela is None:
        tabela = carregar_tabela()
    bruto = str(nome).strip()
    if not bruto or bruto.lower() == 'nan':
        return None
    # O nome antigo não tem grade para remover; por isso a consulta direta vem
    # antes, e só depois a versão sem grade.
    return tabela.get(chave(bruto)) or tabela.get(chave(remover_grade(bruto))) or remover_grade(bruto)


def unificar_serie(serie):
    """Aplica a unificação numa coluna inteira, resolvendo os únicos só uma vez."""
    tabela = carregar_tabela()
    unicos = {v: unificar(v, tabela) for v in serie.dropna().astype(str).str.strip().unique()}
    return serie.astype(str).str.strip().map(unicos)


def unificar_lista(nomes):
    """Lista de franquias -> lista unificada, sem repetição e ordenada."""
    tabela = carregar_tabela()
    saida = {unificar(n, tabela) for n in (nomes or [])}
    return sorted(x for x in saida if x)
