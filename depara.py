import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox
import re
import datetime

def selecionar_arquivo(titulo):
    """Abre uma janela para o usuário selecionar um arquivo."""
    root = tk.Tk()
    root.withdraw() # Oculta a janela principal do tkinter
    caminho = filedialog.askopenfilename(
        title=titulo,
        filetypes=[("Arquivos de Excel/CSV", "*.xlsx *.xls *.csv")]
    )
    return caminho

def extrair_nota_tecnico(valor):
    """Extrai a nota, lidando tanto com tags HTML quanto com números puros."""
    if pd.isna(valor) or str(valor).strip() == '':
        return None
    
    texto = str(valor).strip()
    
    # Caso 1: O valor vem com as tags HTML (ex: >5<)
    match_html = re.search(r'>\s*(\d+)\s*<', texto)
    if match_html:
        return match_html.group(1)
    
    # Caso 2: O valor já vem como número puro (ex: "4", 4 ou "4.0")
    # Caso o pandas leia como float (ex: 4.0), removemos o .0 no final
    if texto.endswith('.0'):
        texto = texto[:-2]
        
    if texto.isdigit():
        return texto
        
    return None

def main():
    # 1. Seleção dos arquivos
    caminho_qualtrics = selecionar_arquivo("1. Selecione a base exportada do Qualtrics")
    if not caminho_qualtrics:
        print("Seleção da base do Qualtrics cancelada.")
        return

    caminho_painel = selecionar_arquivo("2. Selecione a planilha do Painel (NPS Geral)")
    if not caminho_painel:
        print("Seleção do Painel cancelada.")
        return

    print("Processando os dados. Aguarde...")

    # 2. Leitura dos dados
    try:
        # Suporta tanto exportações em CSV quanto Excel do Qualtrics
        if caminho_qualtrics.lower().endswith('.csv'):
            df_qualtrics = pd.read_csv(caminho_qualtrics)
        else:
            df_qualtrics = pd.read_excel(caminho_qualtrics)
            
        df_painel = pd.read_excel(caminho_painel)
    except Exception as e:
        print(f"Erro ao ler os arquivos: {e}")
        return

    # 3. Criação do DataFrame com as novas colunas mapeadas
    df_novos = pd.DataFrame()

    # --- Mapeamento De > Para ---

    if 'ResponseID' in df_qualtrics.columns:
        df_novos['Survey ID'] = df_qualtrics['ResponseID']

    col_data_qualtrics = 'Data de término da pesquisa (registrada) (+00:00 GMT)'
    if col_data_qualtrics in df_qualtrics.columns:
        datas = pd.to_datetime(df_qualtrics[col_data_qualtrics], errors='coerce')
        df_novos['Data de criação local'] = datas
        df_novos['Data da resposta local'] = datas
        df_novos['Data'] = datas.dt.strftime('%d/%m/%Y')

    if 'Q1_NPS' in df_qualtrics.columns:
        df_novos['NPS Purificador BTP'] = df_qualtrics['Q1_NPS']

    if 'Transaction Use Case' in df_qualtrics.columns:
        df_novos['Programa de Pesquisa'] = df_qualtrics['Transaction Use Case']

    if 'Número do caso' in df_qualtrics.columns:
        df_novos['Num OS'] = df_qualtrics['Número do caso']

    if 'ID do cliente' in df_qualtrics.columns:
        df_novos['Contrato'] = df_qualtrics['ID do cliente']

    if 'Franchising' in df_qualtrics.columns:
        df_novos['Franquia'] = df_qualtrics['Franchising']

    if 'Tipo de problema' in df_qualtrics.columns:
        df_novos['Item OS'] = df_qualtrics['Tipo de problema']

    if 'Nome completo do cliente' in df_qualtrics.columns:
        df_novos['Nome Consumidor'] = df_qualtrics['Nome completo do cliente']

    if 'E-mail do destinatário' in df_qualtrics.columns:
        df_novos['Email'] = df_qualtrics['E-mail do destinatário']

    if 'Nome do técnico' in df_qualtrics.columns:
        df_novos['Nome do Técnico'] = df_qualtrics['Nome do técnico']

    if 'Q1_NPS_NPS_GROUP' in df_qualtrics.columns:
        mapa_classificacao = {
            'Promotor': 'Promotores',
            'Passivo': 'Neutros',
            'Depreciador': 'Detratores'
        }
        df_novos['CLASSIFICAÇÃO'] = df_qualtrics['Q1_NPS_NPS_GROUP'].map(mapa_classificacao)

    if 'Q2' in df_qualtrics.columns:
        df_novos['Comentário NPS Ecohouse'] = df_qualtrics['Q2']

    if 'Q14_TechnicianSat_1' in df_qualtrics.columns:
        df_novos['Avaliação do Técnico'] = df_qualtrics['Q14_TechnicianSat_1'].apply(extrair_nota_tecnico)

    # Regras de Negócio e Preenchimentos Específicos
    df_novos['Plataforma'] = 'Qualtrics'

    if 'Vertical da BU' in df_qualtrics.columns:
        df_novos['Forma Jurídica'] = df_qualtrics['Vertical da BU'].fillna('PF')

    if 'Agent Name' in df_qualtrics.columns:
        df_novos['Carteira'] = df_qualtrics['Agent Name']

    # 4. Concatenação da base antiga com os novos dados processados
    df_final = pd.concat([df_painel, df_novos], ignore_index=True)
    
    # 5. Salvar o arquivo final
    caminho_salvar = filedialog.asksaveasfilename(
        title="Salvar Painel Atualizado",
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile="NPS_Geral_Atualizado.xlsx"
    )
    
    if caminho_salvar:
        df_final.to_excel(caminho_salvar, index=False)
        print("Arquivo salvo com sucesso em:", caminho_salvar)
        
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Sucesso", "Painel atualizado e salvo com sucesso!")

if __name__ == "__main__":
    main()