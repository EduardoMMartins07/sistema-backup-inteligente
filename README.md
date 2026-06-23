# Sistema de Backup Inteligente

Sistema desktop para monitorar pastas, gerar backups incrementais e restaurar versões com deduplicação por hash.

## O que faz

- Monitora arquivos em tempo real
- Cria backups incrementais em segundo plano
- Deduplica conteúdo por SHA-256
- Usa snapshots JSON para restauração
- Oferece interface gráfica + ícone na bandeja
- Suporte a login local e controle de permissões
- Integração opcional com AWS S3
- API web básica com FastAPI

## Usar

### Requisitos

- Python 3.13+
- pip
- Windows recomendado

### Instalação

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Executar

```powershell
python main.py
```

Para iniciar a API web:

```powershell
python -m api
```

Acesse `http://127.0.0.1:8000/web/login`.

## Destaques

- backup manual e agendado
- monitoramento contínuo de criação, modificação e exclusão
- snapshots restauráveis
- deduplicação persistente por hash
- progresso de backup em segundo plano
- tratamento de erros parciais sem interromper o backup
- sincronização opcional com S3

## Estrutura principal

- `main.py` — entrada do aplicativo desktop
- `backup/backup_manager.py` — lógica de backup
- `scanner/scanner.py` — análise de arquivos
- `api/` — backend e painel web
- `config/` — configurações e histórico

## Configuração opcional

Use `GEMINI_API_KEY` para ativar classificação inteligente via API.
Use `SMARTBACKUP_JWT_SECRET` para a API central.

## Atalho rápido

- Abra o app
- Configure pastas de origem e destino
- Inicie o scan manual ou deixe o monitoramento agir
- Use o ícone da bandeja para abrir o painel ou encerrar o sistema


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

No primeiro acesso a `http://127.0.0.1:8000/web/login`, o sistema mostra a criacao do admin inicial. Depois disso, usuarios com papel `ADMIN_EMPRESA` acessam o painel administrativo e usuarios comuns acessam `/web/my-backups` para ver apenas os proprios backups. O cookie de sessao usa JWT `HttpOnly` e `SameSite=Lax`; as rotas JSON tambem aceitam `Authorization: Bearer <token>`.

Usuarios criados no painel web tambem podem entrar na aplicacao desktop usando o email como campo **Usuario** e a mesma senha. O login desktop consulta primeiro `config/users.json`; se nao encontrar o usuario local, ele valida a conta ativa no banco SQLite da API e mapeia os papeis `ADMIN_EMPRESA`, `OPERADOR` e `VIEWER` para `admin`, `operator` e `viewer`.

Cada usuario autenticado no desktop recebe um ambiente local isolado em `app_data/companies/company_<company_id>/users/user_<user_id>/`, com `config.json`, `backup_history.json`, `monitored_folders.json`, `backup_state.json`, `backup_schedule.json` e `logs/`. No primeiro uso, arquivos globais antigos em `config/` sao copiados para esse escopo e preservados em `app_data/migration_backup/`; os originais nao sao apagados automaticamente.

Quando um usuario da API executa backup pelo desktop, os metadados da execucao sao sincronizados automaticamente para o SQLite da API. O historico local usa `sync_status = synced`, `pending` ou `failed`, separado de `cloud_sync_status`; se a API estiver offline, o backup local continua valido e a pendencia pode ser reenviada depois.

Se o backup local tiver sido sincronizado com a AWS S3 (`cloud_sync_status = sincronizado` no historico), a tela **Baixar backups** pode recuperar os objetos faltantes da nuvem antes de gerar o ZIP exportado. O historico e as configuracoes usados nessa rotina ficam no escopo local do usuario autenticado.

Endpoints principais:

```text
GET /health
GET /ready
GET /version
POST /setup/first-admin
POST /auth/login
POST /auth/logout
GET  /auth/me
GET  /api/companies/{companyId}/users
GET  /api/companies/{companyId}/backups
GET  /api/me/backups
POST /api/backups
GET  /api/backups/{backupId}
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
