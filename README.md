# Sistema de Backup Inteligente

Aplicacao desktop para acompanhar diretorios importantes, identificar alteracoes nos arquivos e centralizar a rotina de backup em uma interface simples. O sistema combina monitoramento continuo, geracao de dataset com metadados dos arquivos e criacao de backups incrementais com deduplicacao por hash SHA-256, snapshots JSON e restauracao por manifesto.

## Objetivo

Oferecer uma base para backup automatizado e inteligente de arquivos relevantes, permitindo que o usuario configure os diretorios de interesse, acompanhe mudancas no sistema, mantenha um historico das execucoes e tenha copias de seguranca organizadas para consulta e recuperacao futura.

## Regra de Documentacao

Toda alteracao relevante no projeto deve ser refletida neste `README.md`, mantendo a documentacao sempre atualizada com funcionalidades, fluxos, requisitos e mudancas importantes do sistema.

## Stack Tecnologica

- **Runtime:** Python 3.13+
- **Interface Desktop:** Tkinter
- **Monitoramento de arquivos:** watchdog
- **Manipulacao de dados:** pandas
- **Criptografia:** cryptography com AES-256-GCM e PBKDF2-SHA256
- **Compressao de objetos:** gzip (nivel 6) integrado ao pipeline de armazenamento
- **Bandeja do sistema:** pystray
- **Imagens/icones:** pillow
- **Classificacao inteligente:** arvore de decisao local com integracao opcional via Gemini API
- **LLM externa opcional:** Gemini API via REST, usando apenas metadados dos arquivos
- **API central:** FastAPI com SQLite, JWT e templates Jinja2
- **Painel web:** HTML/CSS/JS servido pela propria API
- **Deploy:** Docker, PostgreSQL via `DATABASE_URL`, CORS por ambiente e S3 por variaveis AWS

## Requisitos

- Python 3.13 ou superior
- pip
- Ambiente Windows recomendado
- Chave `GEMINI_API_KEY` opcional para ativar classificacao com Gemini API
- Chave `SMARTBACKUP_JWT_SECRET` recomendada para a API central

## Instalacao e Execucao

1. Clone o repositorio
2. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Instale as dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute a aplicacao:
   ```bash
   python main.py
   ```
5. Para executar a API central e o painel web:
   ```bash
   python -m api
   ```
   Acesse `http://127.0.0.1:8000/web/login`.

## Funcionalidades

- [x] Configuracao inicial e gerenciamento dos diretorios que serao acompanhados pelo sistema
- [x] Monitoramento continuo de criacao, alteracao, remocao e movimentacao de arquivos
- [x] Scanner automatico para varredura dos diretorios monitorados sempre que ha mudancas relevantes
- [x] Geracao de dataset CSV com nome, extensao, tipo, tamanho, tempo desde a ultima modificacao, hash do arquivo e indicador de relevancia
- [x] Marcacao de arquivos duplicados no dataset por hash SHA-256
- [x] Classificacao inicial de arquivos importantes com base em metadados, palavras-chave e contexto do arquivo
- [x] Classificacao por prioridade usando arvore de decisao local e Gemini API com metadados dos arquivos
- [x] Cache local das respostas da LLM para evitar chamadas repetidas para o mesmo arquivo/hash
- [x] Registro observado de modificacoes e acessos entre varreduras para alimentar a arvore de decisao
- [x] Backup manual e backup agendado com armazenamento incremental em `backup_storage/`
- [x] Objetos comprimidos com gzip antes do armazenamento, reduzindo o uso de disco sem impacto na deduplicacao ou na estrutura de indices
- [x] Deduplicacao persistente por hash SHA-256, evitando salvar o mesmo conteudo mais de uma vez
- [x] Snapshots JSON restauraveis para representar o estado logico de cada execucao
- [x] Politica opcional de backup por prioridade: baixa semanal, media a cada 2 dias e alta no inicio do dia + a cada 4 horas quando alterada
- [x] Versionamento automatico dos backups por dia e horario, com organizacao em pastas por data
- [x] Definicao de diretorio padrao para armazenamento dos backups
- [x] Barra de loading / janela de progresso para acompanhamento da execucao do backup
- [x] Execucao do backup em segundo plano para manter a interface responsiva
- [x] Cancelamento seguro da operacao de backup pela interface
- [x] Historico das execucoes de backup e exportacao do artefato mais recente
- [x] Tratamento de falhas parciais durante a copia incremental, ignorando arquivos problematicos sem derrubar toda a execucao
- [x] Protecao contra recursao, ignorando pastas internas do sistema e a propria area de backup
- [x] Interface grafica principal com menu central e suporte por icone na bandeja do sistema
- [x] Icone personalizado aplicado na janela principal, barra de tarefas e bandeja do sistema
- [x] Rodape da interface principal com resumo do ultimo backup e pasta destino
- [x] Bandeja do sistema com informacoes resumidas do ultimo backup e destino atual
- [x] Tooltip da bandeja ajustado para respeitar o limite de caracteres do Windows
- [x] Layout da tela principal ajustado para evitar sobreposicao entre botoes auxiliares e menu
- [x] Login local com criacao automatica do primeiro administrador
- [x] Controle de usuarios por perfil: administrador, operador e visualizador
- [x] API central multiempresa com empresas, usuarios, dispositivos, pastas, backups, snapshots e auditoria em SQLite
- [x] Painel web administrativo para `ADMIN_EMPRESA` com dashboard, usuarios, dispositivos, backups, snapshots e logs
- [x] Preparacao de deploy com `/health`, `/ready`, Dockerfile, Docker Compose, PostgreSQL, CORS, S3 e URL pre-assinada
- [x] Permissoes aplicadas na interface para backup, agendamento, historico, arquivos, configuracoes e usuarios
- [x] Registro do usuario responsavel em cada backup manual
- [x] Logout com retorno para a tela de login
- [x] Historico filtravel por backup com arquivos adicionados, alterados e excluidos
- [x] Visibilidade do historico por perfil: visualizador ve apenas os proprios backups, operador ve os proprios e os de visualizadores, administrador ve todos
- [x] Tela de arquivos analisados com data de inclusao no backup, filtros por coluna e barras de rolagem
- [x] Administrador pode nomear o backup e adicionar descricao antes da execucao manual
- [x] Filtros avancados por janela nas telas de arquivos analisados e historico de backups
- [x] Clique esquerdo no icone da bandeja abre o painel; clique direito mantem o menu de opcoes
- [x] Restauracao de arquivos excluidos, versoes anteriores e snapshots incrementais pela interface
- [x] Busca por nome de arquivo na tela de recuperacao para localizar rapidamente backups relacionados
- [x] Busca com sugestoes de arquivos nas telas de recuperacao e historico de backups
- [x] Tela de arquivos mostra o status de cobertura do backup: em backup, fara backup ou sera excluido no proximo backup
- [x] Criptografia em envelope para backups de usuarios autenticados, com chave mestra por usuario e chave individual por backup/objeto
- [x] Refinamento de UI/UX com fontes padronizadas, botoes com profundidade, scrollbars estilizados, campos mais destacados e abertura suave de janelas
- [x] Melhor legibilidade nas tabelas e caixa de pre-pesquisa com destaque visual para sugestoes de arquivos e pastas
- [ ] Visualizacao do tamanho dos backups e status da ultima execucao
- [ ] Configuracao mais avancada de agendamento
- [x] Integracao completa da classificacao do modulo `ml/` ao scanner e ao fluxo opcional de backup por prioridade

## Exemplos de Uso

### Estrutura dos Backups Gerados

```text
backups/
  backup_storage/
    objects/
      <hash_sha256_1>
      <hash_sha256_2>
    snapshots/
      snapshot_2026-05-08_08-00-00.json
      snapshot_2026-05-08_12-00-00.json
    index.json
```

Os ZIPs gerados por versoes anteriores continuam legiveis para restauracao de historico, mas novas execucoes usam snapshots incrementais como artefato principal.

### Criptografia dos Backups

O sistema utiliza criptografia em envelope. A senha do usuario nao criptografa diretamente os arquivos de backup. Em vez disso, a senha e usada para derivar uma chave criptografica responsavel por proteger uma chave mestra do usuario. Essa chave mestra protege as chaves individuais utilizadas na criptografia dos backups compactados e dos objetos incrementais. Dessa forma, a troca de senha exige apenas a recriptografia da chave mestra, sem necessidade de reprocessar todos os arquivos armazenados.

O algoritmo usado para conteudo e chaves envelopadas e `AES-256-GCM`, com nonces unicos por operacao. A derivacao a partir da senha usa `PBKDF2-SHA256` com salt unico por usuario. A tag de autenticacao do AES-GCM fica embutida no ciphertext gerado pela biblioteca `cryptography`, por isso os metadados registram `auth_tag` como `included_in_ciphertext`.

Metadados sensiveis ficam em arquivos JSON locais:

- `config/users.json`: hash da senha, salt do KDF, chave mestra criptografada e metadados de recuperacao.
- `<backup_destination>/backup_storage/index.json`: metadados dos objetos incrementais, incluindo nonces e chaves de backup criptografadas.
- `config/backup_history.json`: status criptografado, algoritmo usado e caminho do `.zip.enc` quando gerado.

No login, a chave mestra e descriptografada apenas em memoria para a sessao atual. Em backups manuais feitos por usuario autenticado, novos objetos incrementais sao criptografados antes de serem gravados em `backup_storage/objects/`. O sistema tambem gera um artefato compactado criptografado em formato `.zip.enc`, mantendo o ZIP temporario apenas durante a criptografia e apagando-o em seguida.

Na restauracao, o sistema usa a chave de sessao do usuario para abrir a chave do backup/objeto e descriptografar o conteudo antes de copiar para o destino. Se a senha estiver errada, a chave estiver ausente, os metadados forem alterados ou o arquivo estiver corrompido, o AES-GCM falha na autenticacao e a restauracao nao prossegue para aquele item.

Na troca de senha com confirmacao da senha antiga, apenas a chave mestra criptografada e atualizada. Os backups antigos continuam acessiveis porque as chaves de backup continuam protegidas pela mesma chave mestra. Redefinicoes administrativas sem a senha antiga geram nova chave mestra e podem tornar backups criptografados antigos inacessiveis para aquele usuario.

Na criacao de usuario, quando a dependencia de criptografia esta disponivel, o sistema gera uma chave de recuperacao exibida uma unica vez. Essa chave permite redefinir a senha preservando a chave mestra e o acesso aos backups antigos. Se o usuario perder a senha e tambem perder a chave de recuperacao, backups criptografados antigos nao poderao ser descriptografados.

### Integracao AWS S3

O sistema possui integracao com AWS S3 para armazenamento dos backups em nuvem. Os arquivos sao enviados mantendo a organizacao local, separados por empresa, usuario e data. A configuracao fica na opcao **Conexão com Nuvem**, disponivel apenas para administradores; operadores e visualizadores usam a sincronizacao automaticamente durante backups manuais, agendados e por politica de prioridade.

A configuracao e salva em `config/cloud_settings.json`, com a chave secreta criptografada usando uma chave local em `config/cloud_secret.key`. Esses arquivos sao dados locais e ficam fora do Git. A interface mascara a chave secreta e nao registra credenciais em historico ou logs.

O caminho remoto e montado pelo servico central de S3:

```text
backups/<company_id>/<user_id>/<YYYY-MM-DD>/snapshots/<snapshot>.json
backups/<company_id>/<user_id>/<YYYY-MM-DD>/arquivos_relacionados/<hash>
backups/<company_id>/<user_id>/index.json
```

Para usar a nuvem, configure na tela administrativa:

- `AWS Access Key ID`
- `AWS Secret Access Key`
- regiao AWS
- nome do bucket
- prefixo base, por padrao `backups`
- endpoint customizado, opcional
- sincronizacao ativa ou inativa

Permissoes IAM minimas recomendadas para o prefixo configurado:

- `s3:ListBucket`
- `s3:GetObject`
- `s3:PutObject`
- `s3:DeleteObject`

Depois de cada backup, o sistema tenta enviar o snapshot incremental, os objetos relacionados e o indice local para o S3. Se a sincronizacao falhar, o backup local continua valido e o historico registra `cloud_sync_status = falhou` com uma mensagem sanitizada. Quando a nuvem esta desativada, o historico registra `desativado` e nenhum upload e tentado.

Na recuperacao ou exportacao, se o snapshot ou os objetos incrementais nao existirem localmente e o historico indicar sincronizacao concluida, o sistema baixa os arquivos do S3 para a estrutura local antes de restaurar/exportar. A versao usada e a versao registrada no historico do proprio sistema; versionamento nativo por `VersionId` do S3 nao faz parte desta entrega inicial.

### Exemplo de Configuracao

```json
{
  "directories": [
    "C:/Users/super/Documents/Projetos",
    "C:/Users/super/Documents/Contratos"
  ],
  "backup_destination": "C:/Users/super/Backups/SmartBackup",
  "deduplicate_backup": true,
  "llm_classification_enabled": true,
  "llm_cache_enabled": true,
  "gemini_model": "gemini-2.5-flash",
  "priority_backup_policy_enabled": false
}
```

`deduplicate_backup` e mantido por compatibilidade com configuracoes antigas; no fluxo incremental novo a deduplicacao por hash e sempre aplicada.

### Classificacao LLM com Gemini API

O sistema usa a LLM somente com metadados, sem enviar o conteudo completo dos arquivos. A chamada inclui dados como nome, extensao, tamanho, caminho/contexto, hash, dias desde a ultima modificacao e contadores observados de modificacao/acesso.

Para pegar a chave:

1. Acesse a pagina oficial de chaves do Google AI Studio: https://aistudio.google.com/app/apikey
2. Entre com sua conta Google.
3. Clique em `Create API key` ou `Criar chave de API`.
4. Copie a chave gerada e guarde em local seguro.

Referencia oficial do Google: https://ai.google.dev/gemini-api/docs/api-key

Para colocar a chave no projeto, nao salve a chave dentro do codigo. Use uma das duas opcoes abaixo.

Opcao 1: variavel de ambiente do Windows.

No PowerShell, apenas para a sessao atual:

```powershell
$env:GEMINI_API_KEY="SUA_CHAVE_AQUI"
```

No Windows, de forma persistente para o usuario:

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "SUA_CHAVE_AQUI", "User")
```

Depois de configurar de forma persistente, feche e abra novamente o terminal ou reinicie a aplicacao.

Opcao 2: arquivo `.env` local na raiz do projeto.

1. Copie `.env.example` para `.env`.
2. Abra o `.env`.
3. Troque `SUA_CHAVE_AQUI` pela sua chave real:
   ```text
   GEMINI_API_KEY=SUA_CHAVE_AQUI
   GEMINI_MODEL=gemini-2.5-flash
   SMARTBACKUP_LLM_ENABLED=true
   BACKUP_DEV_MODE=false
   ```

O arquivo `.env` fica no `.gitignore` e nao deve ser enviado ao Git. O projeto carrega esse arquivo automaticamente em `ml/llm_classifier.py` sem dependencia extra.

Onde a chave e lida na implementacao:

- `ml/llm_classifier.py`: carrega `.env` e depois le `GEMINI_API_KEY` ou `GOOGLE_API_KEY` pelas variaveis de ambiente.
- `config/config.json`: controla se a classificacao LLM fica ativa com `llm_classification_enabled`.
- `gemini_model`: define o modelo usado. O padrao documentado no projeto e `gemini-2.5-flash`.

Se a chave nao existir, se `llm_classification_enabled` estiver `false` ou se a API falhar, o sistema usa automaticamente a arvore de decisao local como fallback.

### Arvore de Decisao Implementada

A classificacao combina regras locais e, quando disponivel, Gemini API. A arvore considera:

- quantidade observada de modificacoes;
- tipo/extensao do arquivo;
- quantidade observada de acessos;
- nome do arquivo;
- diretorio/contexto onde o arquivo esta inserido.

O resultado gravado em `dataset/files_dataset.csv` inclui:

- `priority`: `baixa`, `media` ou `alta`;
- `priority_score`: pontuacao de 0 a 100;
- `priority_reason`: motivos resumidos da decisao;
- `classification_source`: `rules`, `rules_fallback`, `gemini_api` ou `gemini_cache`;
- `llm_confidence`: confianca retornada/normalizada;
- `backup_policy`: politica derivada da prioridade;
- `decision_tree`: decisoes estruturadas da arvore.

### Politica de Backup por Prioridade

A politica por prioridade fica desativada por padrao para evitar backups automaticos inesperados. Para ativar:

```json
{
  "priority_backup_policy_enabled": true
}
```

Quando ativada, o agendador em segundo plano verifica a politica periodicamente:

- **baixa prioridade:** backup a cada 7 dias;
- **media prioridade:** backup a cada 2 dias;
- **alta prioridade:** backup no primeiro inicio do programa no dia e novamente a cada 4 horas se o arquivo tiver mudado.

Em producao, o agendador checa a politica de prioridade a cada 10 minutos. Com `BACKUP_DEV_MODE=true`, essa checagem passa para 1 minuto para respeitar janelas curtas como `alta = 5 minutos`.

O estado persistente dessa politica fica em `<backup_destination>/backup_storage/index.json`. Backups manuais e agendados avaliam todos os arquivos; backups automaticos por prioridade respeitam as janelas de tempo e registram `skipped_not_eligible` no snapshot quando um arquivo ainda nao deve ser reavaliado.

### DEV MODE para Testes Locais

O projeto aceita um modo de desenvolvimento controlado exclusivamente pela variavel de ambiente `BACKUP_DEV_MODE`. Quando desativado, a politica usa os intervalos reais de producao. Quando ativado, apenas os intervalos de tempo sao reduzidos para facilitar testes locais.

Intervalos usados:

- **producao:** baixa = 7 dias, media = 2 dias, alta = primeiro inicio do dia + a cada 4 horas
- **DEV MODE:** baixa = 30 minutos, media = 15 minutos, alta = 5 minutos

Como ativar no PowerShell:

```powershell
$env:BACKUP_DEV_MODE="true"
python main.py
```

Como desativar no PowerShell:

```powershell
$env:BACKUP_DEV_MODE="false"
python main.py
```

Como ativar no Linux/macOS:

```bash
export BACKUP_DEV_MODE=true
python main.py
```

Como usar no `.env`:

```text
BACKUP_DEV_MODE=true
```

Exemplos de logs:

```text
[DEV MODE] Intervalos reduzidos ativos
[DEV MODE] baixa=30min media=15min alta=5min
[DEV MODE] Arquivo elegivel em intervalo reduzido: contrato.pdf
```

O DEV MODE nao altera prioridade, score, LLM, hash, snapshots, armazenamento incremental, deduplicacao ou restauracao. Ele afeta somente a janela temporal da politica por prioridade.

### Backup Incremental e Restauracao por Snapshot

Cada execucao cria um snapshot JSON em `backup_storage/snapshots/` e salva conteudo fisico apenas quando o hash SHA-256 ainda nao existe em `backup_storage/objects/`. Arquivos inalterados ou duplicados ficam apenas referenciados no snapshot, sem novo objeto fisico.

Para validar a deduplicacao, execute dois backups sem alterar os arquivos e compare a quantidade de arquivos em `backup_storage/objects/`: ela deve permanecer igual enquanto novos snapshots aparecem em `backup_storage/snapshots/`.

Para restaurar um snapshot pela interface, acesse **Recuperar arquivos** e use **Restaurar snapshot**. Pelo codigo, use:

```python
from backup.backup_manager import restore_snapshot

restore_snapshot(
    "C:/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-05-08_12-00-00.json",
    "C:/Restauracao"
)
```

### Exemplo de Historico de Backup

```json
[
  {
    "timestamp": "08/04/2026 19:50:00",
    "backup_file": "snapshot_2026-04-08_19-50-00.json",
    "backup_path": "C:/Users/super/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-04-08_19-50-00.json",
    "snapshot_path": "C:/Users/super/Backups/SmartBackup/backup_storage/snapshots/snapshot_2026-04-08_19-50-00.json",
    "backup_storage": "C:/Users/super/Backups/SmartBackup/backup_storage",
    "storage_mode": "incremental",
    "total_files": 128,
    "objects_stored": 8,
    "objects_referenced": 12,
    "files_unchanged": 108,
    "trigger": "manual",
    "user": "admin",
    "user_role": "admin",
    "file_changes": [
      {
        "action": "adicionado",
        "name": "contrato.pdf",
        "archive_name": "Documentos/contrato.pdf",
        "source_path": "C:/Users/super/Documents/contrato.pdf",
        "size_bytes": 34520,
        "modified_at": "2026-04-08T19:48:12"
      }
    ]
  }
]
```

### Perfis de Usuario

- **Administrador:** acessa todas as funcionalidades, incluindo gerenciamento de usuarios, diretorios e destino de backup.
- **Operador:** pode realizar backup, agendar backup, visualizar arquivos, consultar historico e baixar o ultimo backup.
- **Visualizador:** possui acesso somente leitura aos arquivos analisados e ao historico de backups.
- **Sem login:** nao acessa o painel nem executa acoes protegidas.

Os usuarios ficam em `config/users.json`. As senhas nao sao salvas em texto puro; o sistema armazena hash PBKDF2 com salt individual.

### Filtro de Historico por Perfil

- **Visualizador:** visualiza somente backups executados pelo proprio usuario e seus arquivos adicionados, alterados ou excluidos.
- **Operador:** visualiza os proprios backups e backups executados por visualizadores.
- **Administrador:** visualiza backups de administradores, operadores, visualizadores e execucoes do sistema.

Cada backup novo registra um snapshot dos arquivos e compara com o snapshot anterior para montar a lista de mudancas. Backups antigos, criados antes dessa funcionalidade, podem aparecer sem detalhes de mudancas.

### Execucao do Backup na Interface

- Ao iniciar um backup manual, a aplicacao abre uma barra de loading para acompanhar o progresso da operacao.
- O processamento acontece em segundo plano para evitar que a interface principal fique travada.
- O usuario pode cancelar a operacao durante o scanner ou durante a copia dos objetos incrementais.
- Se o cancelamento ocorrer no meio da execucao, o sistema encerra o processo com seguranca e remove arquivos parciais de backup.

### API Central e Painel Web Multiempresa

O projeto tambem possui uma API central em `api/`, separada do fluxo desktop local. Ela usa SQLite para registrar empresas, usuarios, dispositivos, pastas monitoradas, backups, snapshots e auditoria. O painel web fica em `/web/*` e e servido pela propria API com templates Jinja2.

Variaveis principais:

```text
SMARTBACKUP_API_DB_PATH=config/api.sqlite3
SMARTBACKUP_API_STORAGE_ROOT=api_storage
SMARTBACKUP_API_STORAGE_BACKEND=local
SMARTBACKUP_API_BASE_S3_PREFIX=backups
SMARTBACKUP_JWT_SECRET=troque-esta-chave-em-producao
SMARTBACKUP_JWT_EXPIRE_MINUTES=1440
```

Comando para iniciar:

```bash
python -m api
```

No primeiro acesso a `http://127.0.0.1:8000/web/login`, o sistema mostra a criacao do admin inicial. Depois disso, apenas usuarios com papel `ADMIN_EMPRESA` acessam o painel web. O cookie de sessao usa JWT `HttpOnly` e `SameSite=Lax`; as rotas JSON tambem aceitam `Authorization: Bearer <token>`.

Usuarios criados no painel web tambem podem entrar na aplicacao desktop usando o email como campo **Usuario** e a mesma senha. O login desktop consulta primeiro `config/users.json`; se nao encontrar o usuario local, ele valida a conta ativa no banco SQLite da API e mapeia os papeis `ADMIN_EMPRESA`, `OPERADOR` e `VIEWER` para `admin`, `operator` e `viewer`.

Quando um usuario da API executa backup pelo desktop, os metadados da execucao sao sincronizados automaticamente para o SQLite da API. Assim, o painel web passa a listar o backup sem receber os arquivos diretamente. A sincronizacao depende de o usuario do desktop ter sido criado no painel web e estar entrando com o email cadastrado.

Se o backup local tiver sido sincronizado com a AWS S3 (`cloud_sync_status = sincronizado` no historico), a tela **Baixar backups** pode recuperar os objetos faltantes da nuvem antes de gerar o ZIP exportado. O arquivo `config/backup_history.json` e as credenciais/configuracoes da nuvem precisam continuar disponiveis.

Endpoints principais:

```text
GET /health
GET /ready
GET /version
POST /setup/first-admin
POST /auth/login
POST /auth/logout
GET  /auth/me
POST /devices/register
POST /monitored-folders
POST /backups
POST /backups/presigned-url
POST /backups/{backupId}/upload
PATCH /backups/{backupId}/finish
GET  /backups
GET  /backups/{backupId}
POST /snapshots
GET  /snapshots
GET  /backups/{backupId}/snapshots
GET  /admin/dashboard
GET  /admin/users
POST /admin/users
PATCH /admin/users/{userId}
DELETE /admin/users/{userId}
GET  /admin/users/{userId}/backups
GET  /admin/devices/{deviceId}/backups
GET  /admin/audit-logs
```

Exemplo de login:

```json
{
  "email": "usuario@empresa.com",
  "password": "senha"
}
```

Exemplo de registro de dispositivo:

```json
{
  "name": "Notebook Joao",
  "hostname": "JOAO-PC",
  "identifier": "uuid-gerado-no-agente"
}
```

Exemplo de criacao de backup pelo agente:

```json
{
  "deviceId": "device_id",
  "folderId": "folder_id",
  "name": "backup-2026-05-23-10-00.zip",
  "type": "INCREMENTAL",
  "priority": "HIGH",
  "sizeBytes": 10485760,
  "fileCount": 25,
  "checksum": "sha256_hash",
  "metadata": {
    "os": "Windows",
    "agentVersion": "1.0.0",
    "compressed": true,
    "encrypted": true
  }
}
```

A API nunca confia em `companyId` vindo do cliente. Empresa, usuario e papel sao definidos pelo token JWT. Todas as consultas sensiveis filtram por `company_id`, e operadores so manipulam backups dos proprios dispositivos.

Para deploy e operacao online, consulte:

- `README_ENV.md`: variaveis de ambiente.
- `README_API.md`: endpoints e exemplos.
- `README_DEPLOY_ZERO_COST.md`: caminho recomendado com Render + Neon + R2.
- `README_DEPLOY_RENDER.md`: deploy no Render.
- `README_DEPLOY_RAILWAY.md`: deploy no Railway.
- `README_DEPLOY_DOCKER.md`: Docker/VPS com PostgreSQL.

Comandos uteis da API:

```bash
python -m api.manage migrate
python -m api.manage check-env
python -m api.manage seed
```

### Fluxo Atual da Aplicacao

1. O usuario seleciona os diretorios na interface.
2. O sistema monitora alteracoes nesses diretorios.
3. Quando um arquivo e criado, alterado, removido ou movido, o scanner atualiza o dataset, registra hash, duplicidade, contadores observados e classificacao por prioridade.
4. Quando o backup e iniciado manualmente ou por agendamento, a aplicacao abre uma janela de progresso sem travar a interface principal.
5. O usuario pode acompanhar o andamento e cancelar a operacao de forma segura durante o scanner ou a copia de objetos.
6. O sistema calcula o SHA-256 de cada arquivo avaliado e copia para `objects/` somente hashes ainda inexistentes.
7. Cada execucao cria um snapshot em `snapshots/` e atualiza `index.json` com o ultimo hash, prioridade e data de backup de cada arquivo.
8. Se `priority_backup_policy_enabled` estiver ativado, o agendador cria snapshots respeitando as janelas de prioridade.
9. O sistema registra o historico da execucao e permite exportar o ultimo artefato de backup.
10. A interface permite consultar arquivos excluidos ou alterados por backup, recuperar itens a partir de backups anteriores e restaurar snapshots completos.
11. Ao recuperar, arquivos existentes no destino sao comparados por hash; conflitos podem ser renomeados, usando `_recuperado` como nome padrao.

## Estrutura do Projeto

- `main.py`: ponto de entrada da aplicacao.
- `api/`: API central FastAPI, banco SQLite, rotas JSON, painel web e templates administrativos.
- `auth/`: autenticacao local, hash de senhas e regras de permissao por perfil.
- `interface/gui.py`: interface principal e janelas auxiliares.
- `interface/login.py`: login e criacao do primeiro administrador.
- `scanner/scanner.py`: varredura dos diretorios, calculo de hash e geracao do dataset CSV.
- `ml/llm_classifier.py`: classificacao por arvore local e Gemini API usando metadados dos arquivos.
- `monitor/monitor.py`: monitoramento de alteracoes com watchdog.
- `backup/backup_manager.py`: criacao incremental, deduplicacao persistente, snapshots, historico e restauracao dos backups.
- `utils/file_hash.py`: calculo de hash SHA-256 para identificacao de duplicados.
- `scheduler/scheduler.py`: execucao automatica de backups agendados.
- `tray/tray_icon.py`: integracao com bandeja do sistema.
- `assets/`: arquivos visuais usados pela interface, como o icone da aplicacao.
- `config/`: arquivos de configuracao, historico, agendamento, cache da LLM e estado da politica por prioridade.
- `dataset/`: CSV gerado pelo scanner.
- `backups/`: destino padrao local dos backups; novas execucoes criam `backup_storage/` dentro dele.
- `ml/`: modulos de classificacao local e integracao opcional com Gemini API.

## Proximos Passos Sugeridos

- [x] Adicionar restauracao de backup e versoes anteriores pela interface
- [ ] Mostrar tamanho, data e origem do ultimo backup na tela principal
- [ ] Permitir exclusao ou limpeza de backups antigos
- [ ] Melhorar o menu da bandeja para disparar backup completo e nao apenas scan
- [ ] Exibir logs mais detalhados na interface
- [x] Integrar classificacao de relevancia usando o modulo `ml/`
- [x] Deduplicacao persistente no fluxo incremental
- [x] Adicionar um controle visual na interface para ativar ou desativar `priority_backup_policy_enabled`
- [ ] Adicionar troca de senha pelo proprio usuario

## Comandos Uteis

- `python main.py`: inicia a aplicacao.
- `python -m api`: inicia a API central e o painel web em `http://127.0.0.1:8000`.
- `python -m api.manage migrate`: aplica a migration versionada da API.
- `render.yaml`: Blueprint do Render para subir a API com variaveis prontas para preencher.
- `docker compose up -d --build`: sobe PostgreSQL e API para desenvolvimento com Docker.
- `python -m py_compile main.py auth/users.py auth/permissions.py monitor/monitor.py interface/login.py interface/gui.py backup/backup_manager.py scheduler/scheduler.py scanner/scanner.py utils/file_hash.py ml/llm_classifier.py api/app.py api/config.py api/database.py api/dependencies.py api/schemas.py api/security.py api/services.py api/storage.py api/manage.py api/logging_config.py api/local_history_sync.py`: valida a sintaxe dos modulos principais.
- `python -m unittest discover -s tests`: executa os testes automatizados do backup incremental.
- `python scanner/scanner.py`: executa o scanner manualmente.
- `pip install -r requirements.txt`: instala as dependencias do projeto.
