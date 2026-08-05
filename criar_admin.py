"""
Script de primeiro acesso do Painel NPS.

Existe por causa do ovo-e-galinha: a tela de administracao so aparece para
usuarios do tipo 'admin', e no banco recem-criado nao existe nenhum. Este
script cria as tabelas e o primeiro administrador.

Rode UMA vez, no seu computador, dentro da pasta do projeto:

    python criar_admin.py

Depois disso todos os demais cadastros sao feitos pela aba "Usuarios" do painel.
"""

import sys
import getpass
import re
from pathlib import Path

try:
    import bcrypt
    from sqlalchemy import create_engine, text
except ImportError:
    sys.exit("Faltam dependencias. Rode antes:  pip install -r requirements.txt")

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        sys.exit("Python 3.11+ necessario, ou rode:  pip install tomli")

CAMINHO_SECRETS = Path(".streamlit/secrets.toml")


def carregar_url():
    if not CAMINHO_SECRETS.exists():
        sys.exit(
            f"Arquivo {CAMINHO_SECRETS} nao encontrado.\n"
            "Copie .streamlit/secrets.toml.exemplo para .streamlit/secrets.toml "
            "e preencha a connection string do Neon."
        )
    with open(CAMINHO_SECRETS, "rb") as f:
        dados = tomllib.load(f)
    try:
        url = dados["connections"]["postgresql"]["url"]
    except KeyError:
        sys.exit("Nao encontrei [connections.postgresql] -> url no secrets.toml.")
    if "COLOQUE" in url or "USUARIO:SENHA" in url:
        sys.exit("A connection string ainda esta com os valores de exemplo. Preencha com os dados do Neon.")
    return url


def formatar_telefone(tel):
    numeros = re.sub(r"\D", "", str(tel))
    if 10 <= len(numeros) <= 11:
        numeros = "55" + numeros
    return numeros


DDL = [
    """CREATE TABLE IF NOT EXISTS nps_usuarios (
        id SERIAL PRIMARY KEY,
        usuario TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        nome TEXT NOT NULL,
        email TEXT,
        perfil TEXT,
        tipo TEXT NOT NULL DEFAULT 'comum',
        telefone TEXT,
        ativo BOOLEAN DEFAULT TRUE,
        token_sessao TEXT,
        token_expira_em TIMESTAMP,
        reset_token TEXT,
        reset_token_expira TIMESTAMP,
        ultimo_acesso TIMESTAMP,
        criado_em TIMESTAMP DEFAULT NOW()
    );""",
    """CREATE TABLE IF NOT EXISTS nps_usuario_franquias (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES nps_usuarios(id) ON DELETE CASCADE,
        franquia TEXT NOT NULL,
        UNIQUE (usuario_id, franquia)
    );""",
    """CREATE TABLE IF NOT EXISTS nps_logs (
        id SERIAL PRIMARY KEY,
        data TIMESTAMP DEFAULT NOW(),
        responsavel TEXT,
        acao TEXT,
        detalhes TEXT
    );""",
    "CREATE INDEX IF NOT EXISTS idx_nps_uf_usuario ON nps_usuario_franquias(usuario_id);",
]


def main():
    url = carregar_url()
    engine = create_engine(url, pool_pre_ping=True)

    print("Conectando ao Neon...")
    with engine.begin() as cx:
        for comando in DDL:
            cx.execute(text(comando))
    print("Tabelas criadas/verificadas: nps_usuarios, nps_usuario_franquias, nps_logs\n")

    with engine.connect() as cx:
        qtd = cx.execute(text("SELECT COUNT(*) FROM nps_usuarios WHERE tipo = 'admin'")).scalar()
    if qtd:
        print(f"Ja existem {qtd} administrador(es) cadastrado(s).")
        if input("Criar mais um mesmo assim? (s/N): ").strip().lower() != "s":
            print("Nada foi alterado.")
            return

    print("--- Cadastro do administrador ---")
    usuario = input("Usuario (login): ").strip()
    nome = input("Nome completo: ").strip()
    email = input("E-mail: ").strip()
    telefone = input("Celular com DDD (recebera o codigo 2FA): ").strip()
    senha = getpass.getpass("Senha: ")
    senha2 = getpass.getpass("Confirme a senha: ")

    if not usuario or not nome:
        sys.exit("Usuario e nome sao obrigatorios.")
    if senha != senha2:
        sys.exit("As senhas nao conferem.")
    if len(senha) < 6:
        sys.exit("A senha deve ter ao menos 6 caracteres.")
    tel_fmt = formatar_telefone(telefone)
    if len(tel_fmt) < 12:
        sys.exit(f"Telefone invalido ('{tel_fmt}'). Informe DDD + numero, ex.: 11987654321")

    senha_hash = bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    with engine.begin() as cx:
        existe = cx.execute(
            text("SELECT id FROM nps_usuarios WHERE LOWER(usuario) = LOWER(:u)"), {"u": usuario}
        ).fetchone()
        if existe:
            sys.exit(f"O usuario '{usuario}' ja existe.")
        cx.execute(
            text("""INSERT INTO nps_usuarios (usuario, senha, nome, email, perfil, tipo, telefone)
                    VALUES (:u, :s, :n, :e, 'Administrador', 'admin', :tel)"""),
            {"u": usuario, "s": senha_hash, "n": nome, "e": email, "tel": tel_fmt},
        )
        cx.execute(
            text("INSERT INTO nps_logs (responsavel, acao, detalhes) VALUES (:r, :a, :d)"),
            {"r": "Setup", "a": "Admin inicial", "d": f"Criado via criar_admin.py: {usuario}"},
        )

    print(f"\nAdministrador '{usuario}' criado com sucesso.")
    print("Agora rode o painel:  streamlit run NPS_app.py")
    print("Depois de logar, use a aba 'Usuarios' > 'Importar planilha' para carregar os 31 franqueados.")


if __name__ == "__main__":
    main()
