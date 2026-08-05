# Guia de configuração — Painel NPS

Passo a passo para colocar o painel no ar. A ordem importa: o banco precisa
existir antes do primeiro login.

---

## Parte 1 — Criar o projeto no Neon

Você optou por um **projeto novo**, separado do da Lojinha. Isso garante que um
problema no painel de NPS não encoste nos dados da lojinha.

### 1.1 Criar o projeto

1. Acesse **https://console.neon.tech** e entre com a mesma conta da Lojinha.
2. No canto superior, abra o seletor de projetos e clique em **New Project**.
3. Preencha:
   - **Project name:** `painel-nps`
   - **Postgres version:** deixe a padrão (16 ou superior)
   - **Region:** escolha a mesma da Lojinha (provavelmente `AWS US East (Ohio)`).
     Região diferente não quebra nada, mas adiciona latência.
4. Clique em **Create project**.

> **Atenção ao plano gratuito.** O Free Tier do Neon permite um número limitado
> de projetos. Se o botão de criar vier bloqueado, é porque o limite já foi
> atingido com o projeto da Lojinha — nesse caso me avise que eu adapto a
> configuração para usar um *database* separado dentro do mesmo projeto.

### 1.2 Copiar a connection string

Ao terminar a criação, o Neon já mostra a caixa **Connection string**
(se fechar, clique em **Connect** no painel do projeto).

1. Confirme que o seletor de branch está em **main** e o database em **neondb**.
2. Deixe a opção **Connection pooling** ligada — ela é importante para o
   Streamlit, que abre e fecha conexões a cada rerun.
3. Copie a string. Ela tem este formato:

```
postgresql://neondb_owner:AbC123xyz@ep-cool-name-12345678-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
```

> A senha aparece só nesse momento. Se perder, use **Reset password** na mesma tela.

### 1.3 Ajustar a string para o SQLAlchemy

O Streamlit acessa o Postgres via SQLAlchemy, que precisa saber qual driver usar.
**Troque o prefixo:**

| De | Para |
|---|---|
| `postgresql://` | `postgresql+psycopg2://` |

Ficando assim:

```
postgresql+psycopg2://neondb_owner:AbC123xyz@ep-cool-name-12345678-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
```

Guarde o `?sslmode=require` no final — o Neon recusa conexão sem TLS.

---

## Parte 2 — Configurar os segredos localmente

1. Na pasta do projeto, copie `.streamlit/secrets.toml.exemplo` para
   `.streamlit/secrets.toml`.
2. Preencha os três blocos:
   - `APP_URL` — a URL pública do app (usada no link de reset de senha por SMS).
   - `INFOBIP_BASE_URL` e `INFOBIP_API_KEY` — os mesmos valores da Lojinha.
   - `[connections.postgresql] url` — a string do passo 1.3.

O `.gitignore` já bloqueia o `secrets.toml`, então ele nunca vai para o GitHub.

---

## Parte 3 — Criar as tabelas e o primeiro administrador

Você não consegue entrar no painel sem um usuário admin, e não consegue criar
um usuário admin pelo painel sem estar logado. O script resolve esse impasse.

```bash
pip install -r requirements.txt
```

```bash
python criar_admin.py
```

O script cria as três tabelas e pede seus dados. **Use um celular real** — é
para lá que vai o código 2FA no primeiro login.

Tabelas criadas:

| Tabela | Conteúdo |
|---|---|
| `nps_usuarios` | login, hash da senha, telefone, tipo (`admin`/`comum`), tokens de sessão |
| `nps_usuario_franquias` | vínculo usuário → franquia (uma linha por franquia) |
| `nps_logs` | auditoria: login, alterações de cadastro, resets de senha |

Para conferir, abra o **SQL Editor** no menu lateral do Neon e rode:

```sql
SELECT usuario, nome, tipo, telefone FROM nps_usuarios;
```

---

## Parte 4 — Rodar e carregar os usuários

```bash
streamlit run NPS_app.py
```

1. Faça login com o admin que você criou. Vai chegar um SMS com 6 dígitos.
2. Vá na aba **⚙️ Usuários → Importar planilha**.
3. Confira o resumo (quantas franquias de cada usuário existem na base de NPS)
   e clique em **Executar importacao**. Os 31 franqueados entram como `comum`.
4. Vá em **Usuários** e **cadastre o telefone de cada um**. Sem telefone o
   login é bloqueado, porque não há como enviar o código 2FA.

Para enviar as credenciais: selecione o usuário e clique em
**Resetar senha e enviar SMS** — ele recebe uma senha provisória por mensagem.

---

## Parte 5 — Publicar no Streamlit Cloud

1. Suba o projeto para um repositório no GitHub (o `.bat` de atualização já faz
   `add`/`commit`/`push`). Confirme que `secrets.toml` **não** foi junto.
2. Em **share.streamlit.io**, crie o app apontando para `NPS_app.py`.
3. Em **Manage app → Settings → Secrets**, cole o conteúdo do seu
   `secrets.toml` local.
4. Volte no `APP_URL` do secrets e ajuste para a URL definitiva do app.

Os arquivos `NPS Geral.xlsx` e `NPS Classificado.xlsx` continuam no repositório,
como hoje — nada de NPS vai para o banco. O Neon guarda **somente** usuários,
permissões e logs.

---

## Envio do código 2FA (WhatsApp)

O código de verificação vai por **WhatsApp**, usando o template HSM `nps_acesso`.
SMS ficou só como reserva.

**Por que não SMS:** o remetente era o ID alfanumérico `"InfoSMS"`, e operadoras
brasileiras bloqueiam esse formato. A Infobip aceitava com HTTP 200 e a mensagem
morria depois, sem erro nenhum aparecer no app.

### O detalhe que custou caro

O `nps_acesso` é da categoria **Autenticação**. Nessa categoria o WhatsApp exige
que o código vá **também no botão de copiar**, não só no corpo — e a Infobip
expõe esse botão como `type: "URL"`, não `COPY_CODE` como o nome sugeriria.

Descoberto por eliminação: quatro variantes foram disparadas para o mesmo número,
cada uma com um código diferente. **Todas retornaram HTTP 200 / PENDING_ENROUTE.
Só a `URL` chegou no aparelho.** As outras três foram descartadas em silêncio.

Configuração correta, já fixada no `secrets.toml`:

```toml
TEMPLATE_2FA = "nps_acesso"
TEMPLATE_2FA_IDIOMA = "pt_BR"
TEMPLATE_2FA_BOTAO = "URL"
FALLBACK_SMS = true
```

> **Regra geral com a Infobip:** resposta HTTP 200 não significa entrega. O status
> real vem em `messages[0].status.groupName` — e mesmo `PENDING_ENROUTE` pode não
> chegar. Só o aparelho confirma. Essa mesma armadilha já tinha aparecido na
> lojinha, com o idioma `pt_PT`.

Se um dia o template mudar, a aba **⚙️ Usuários → Diagnóstico de envio** varre as
combinações de idioma e botão e imprime o bloco pronto para colar no `secrets.toml`.

---

## Como funciona o controle de acesso

Três perfis, gravados na coluna `tipo` de `nps_usuarios`:

| | `admin` | `operacao` | `comum` |
|---|:---:|:---:|:---:|
| Vê todas as franquias | ✅ | ✅ | ❌ (só as vinculadas) |
| Análises Avançadas (senha `1010`) | ✅ | ✅ | ❌ |
| Aba Usuários | edita | **consulta** | não vê |
| Criar usuário / importar planilha | ✅ | ❌ | ❌ |
| Salvar, resetar senha, excluir | ✅ | ❌ | ❌ |
| Diagnóstico de envio e Auditoria | ✅ | ✅ | ❌ |

**Comum** — o painel filtra `df_geral` e `df_classificado` pelas franquias
vinculadas ao usuário **antes de qualquer cálculo**. Todos os indicadores, KPIs
e gráficos já nascem restritos; não existe caminho pelo qual um franqueado veja
número de outro. O seletor de franquias no menu lateral também só lista as dele.

O casamento é por **nome exato** da franquia, conforme você decidiu.

**Operação** — enxerga exatamente o que o admin enxerga nos dados, mas a aba
Usuários entra em modo consulta: as abas de criação e importação não aparecem, e
todos os campos de edição vêm desabilitados. Não há botão de salvar, resetar
senha ou excluir.

> Um `tipo` desconhecido no banco cai em `comum` — a falha é sempre para o menor
> privilégio, nunca para o maior.

Para criar um usuário de Operação: aba **⚙️ Usuários → Novo usuário**, campo
**Tipo de acesso** → `operacao`. Não precisa vincular franquias.

---

## Ponto de atenção sobre os nomes das franquias

A base de NPS usa duas nomenclaturas diferentes:

- **Qualtrics (atual):** `FRQ CAMPINAS R02`, `AT FORTALEZA CE R01 - MATRIZ`
- **Medallia (legado):** `FRQ_ECO_SP_CAMPINAS_2`, `AT_ECO_CE_FORTALEZA`

A planilha de usuários usa só a nomenclatura Qualtrics. Como o casamento é
exato, **5.510 das 9.609 respostas (57%) ficam invisíveis para usuários comuns** —
praticamente todo o histórico Medallia. O admin continua vendo tudo.

Visibilidade por usuário depois da importação:

| Usuário | Franquias na planilha | Casadas | Respostas visíveis |
|---|---:|---:|---:|
| jvent.ventura | 37 | 28 | 1.270 |
| opera.pereira / sibel.sibele / simon.simone | 16 | 12 | 1.003 |
| guede.guedes | 26 | 19 | 462 |
| mauro.celso | 6 | 6 | 458 |
| james.castro | 8 | 5 | 425 |
| logis.araujo | 21 | 14 | 401 |
| alexa.duo | 23 | 17 | 387 |
| jcich.cichy / rdsil.silva | 6 | 4 | 380 |
| aer.b.carlos / aer.c.cesar | 31 | 22 | 208 |
| carlo.carlos / rhend.gomes | 6 | 4 | 201 |
| evert.leite / fpint.pinto | 15 | 10 | 162 |
| claud.claudio / tatia.oliveira | 5 | 4 | 85 |
| brast.roger / diret.karenine | 7 | 4 | 76 |
| Felip.felipe | 5 | 5 | 61 |
| alexa.machado | 4 | 4 | 58 |
| falte.deysi / sueny.falcone | 4 | 2 | 18 |
| garan.ester / ouvid.sandro | 6 | 4 | 13 |
| allan.bezerra / natal.thalia | 3 | 3 | 6 |
| **frima.frank / maril.frank** | 5 | **1** | **3** |

Frank e Marilene ficam com 3 respostas — na prática, um painel vazio.

Há ainda **29 franquias na base sem nenhum dono** na planilha, entre elas
`FRQ GOIANIA GO R01/R02/R03`, `FRQ LAGOS RJ`, `FRQ OESTE RJ`,
`FRQ BRAGANCA PAULISTA SP R02/R03/R05` e `FRQ GUARULHOS SP R04`.

Nada disso bloqueia o uso do painel. Quando quiser resolver, dá para tratar de
duas formas: completar a planilha de usuários com as franquias sem dono, ou
montar uma tabela de-para ligando os nomes Medallia aos Qualtrics — é só me
avisar que eu preparo.
