"""
Leitura de Excel segura quando várias pessoas abrem o painel ao mesmo tempo.

No Streamlit cada sessão roda numa thread própria. Logo depois que o app
reinicia (deploy, reboot, atualização das bases), várias sessões chegam juntas
e o pandas tenta carregar o openpyxl em todas ao mesmo tempo. No Python 3.14
do Streamlit Cloud isso às vezes devolve o módulo pela metade e a leitura
quebra com:

    partially initialized module 'openpyxl' ... has no attribute 'Workbook'

Duas proteções resolvem:
1. O openpyxl é importado por inteiro aqui, uma única vez, quando este módulo
   é carregado — antes de qualquer leitura.
2. As leituras de Excel entram em fila (uma de cada vez). Como as bases ficam
   em cache, isso só acontece na primeira carga e não deixa o painel lento.

Use ler_excel() no lugar de pd.read_excel() em todo o projeto.
"""

import threading

import openpyxl  # noqa: F401  (carregado por inteiro de propósito; ver acima)
import pandas as pd

_trava = threading.Lock()


def ler_excel(caminho, **kwargs):
    """pd.read_excel com o motor openpyxl, uma leitura por vez."""
    kwargs.setdefault("engine", "openpyxl")
    with _trava:
        return pd.read_excel(caminho, **kwargs)
