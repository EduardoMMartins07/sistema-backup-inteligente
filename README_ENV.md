# Variaveis de Ambiente

Copie `.env.example` para `.env` em desenvolvimento. Em producao, configure as variaveis diretamente na plataforma.

| Nome | Obrigatoria | Exemplo | Uso | Descricao |
| --- | --- | --- | --- | --- |
| `SMARTBACKUP_ENV` | Nao | `production` | API | Ambiente da aplicacao. Em `production`, variaveis criticas sao validadas no boot. |
| `PORT` | Sim em producao | `8000` | API | Porta HTTP usada pelo Uvicorn. |
| `API_BASE_URL` | Nao | `https://api.seudominio.com` | Painel/agente | URL publica da API. |
| `API_URL` | Nao | `https://api.seudominio.com` | Agente | URL que o agente local deve usar para login, device e backups. |
| `DATABASE_URL` | Sim em producao | `postgresql://user:pass@host:5432/db` | API | Banco principal. Use PostgreSQL em deploy e `sqlite:///config/api.sqlite3` localmente. |
| `SMARTBACKUP_API_DB_PATH` | Nao | `config/api.sqlite3` | API local | Caminho SQLite quando `DATABASE_URL` nao aponta para PostgreSQL. |
| `JWT_SECRET` | Sim em producao | `valor-longo-aleatorio` | Auth | Chave de assinatura JWT. Nunca use o valor de exemplo em producao. |
| `SMARTBACKUP_JWT_SECRET` | Nao | `valor-longo-aleatorio` | Auth | Alias compativel com a implementacao local. |
| `JWT_EXPIRES_IN` | Nao | `7d` | Auth | Duracao textual do token. Aceita `d`, `h`, `m` ou minutos. |
| `JWT_EXPIRES_MINUTES` | Nao | `10080` | Auth | Duracao do token em minutos. |
| `AWS_ACCESS_KEY_ID` | Sim em producao | `AKIA...` | S3 | Chave de acesso AWS. |
| `AWS_SECRET_ACCESS_KEY` | Sim em producao | `secret` | S3 | Chave secreta AWS. Nao commitar. |
| `AWS_REGION` | Sim em producao | `sa-east-1` | S3 | Regiao do bucket. |
| `AWS_S3_BUCKET` | Sim em producao | `smart-backup-prod` | S3 | Bucket usado para URLs pre-assinadas. |
| `AWS_ENDPOINT_URL` | Nao | `https://s3.local` | S3 | Endpoint customizado para MinIO/compativeis. |
| `SMARTBACKUP_API_BASE_S3_PREFIX` | Nao | `backups` | S3 | Prefixo raiz dos objetos. |
| `PRESIGNED_URL_EXPIRES_SECONDS` | Nao | `900` | S3 | Expiracao das URLs pre-assinadas. |
| `CORS_ORIGIN` | Sim em producao | `https://painel.seudominio.com` | API | Origens permitidas separadas por virgula. Evite `*` em producao. |
| `MAX_UPLOAD_SIZE_MB` | Nao | `500` | Upload | Limite de upload via backend e metadados para presigned URL. |
| `SMARTBACKUP_API_STORAGE_ROOT` | Nao | `api_storage` | Local | Pasta de uploads locais quando nao usar S3 direto. |
| `SEED_ADMIN_PASSWORD` | Nao | `senha-forte` | Seed | Senha do admin demo. Obrigatoria apenas para `python -m api.manage seed`. |
| `SEED_OPERATOR_PASSWORD` | Nao | `senha-forte` | Seed | Senha opcional do operador demo. |
| `SEED_VIEWER_PASSWORD` | Nao | `senha-forte` | Seed | Senha opcional do viewer demo. |
| `GEMINI_API_KEY` | Nao | `...` | Desktop | Ativa classificacao LLM no desktop. |
| `BACKUP_DEV_MODE` | Nao | `false` | Desktop | Reduz janelas de backup por prioridade para testes. |

## Validacao

Em producao, defina:

```bash
SMARTBACKUP_ENV=production
```

A API falha no boot se `DATABASE_URL`, `JWT_SECRET`, variaveis AWS e `PORT` nao estiverem configurados. Para validar manualmente:

```bash
python -m api.manage check-env
python -m api.manage check-env --strict
```

Sem `--strict`, o comando apenas avisa em desenvolvimento. Em producao,
ou com `--strict`, ele retorna erro quando variaveis obrigatorias estiverem
ausentes.
