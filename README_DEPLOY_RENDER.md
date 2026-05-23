# Deploy no Render

## Opcao recomendada

Para custo inicial menor, prefira o fluxo documentado em `README_DEPLOY_ZERO_COST.md`,
usando Render para a API, Neon para PostgreSQL e Cloudflare R2 como bucket S3 compativel.

## 1. Preparar Repositorio

1. Suba o projeto para o GitHub.
2. Confirme que `.env` nao foi commitado.
3. Garanta que `Dockerfile`, `.dockerignore`, `requirements.txt` e `render.yaml` estao versionados.

## 2. Banco PostgreSQL

1. Crie um PostgreSQL no Render ou use um provedor externo.
2. Copie a `DATABASE_URL` interna/externa.

## 3. Web Service

1. Crie um novo **Web Service** no Render apontando para o repositorio.
2. Escolha deploy via Docker.
3. Se preferir, use **Blueprint** para o Render ler `render.yaml` automaticamente.
4. Configure:

```txt
Build Command: vazio quando usar Dockerfile
Start Command: python -m api.manage migrate && python -m uvicorn api.app:app --host 0.0.0.0 --port $PORT
```

## 4. Variaveis

Configure:

```txt
SMARTBACKUP_ENV=production
PORT=10000
API_BASE_URL=https://sua-api.onrender.com
DATABASE_URL=postgresql://...
JWT_SECRET=valor-longo-e-aleatorio
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=sa-east-1
AWS_S3_BUCKET=...
CORS_ORIGIN=https://sua-api.onrender.com
MAX_UPLOAD_SIZE_MB=500
```

## 5. Validacao

Depois do deploy:

```bash
curl https://sua-api.onrender.com/health
curl https://sua-api.onrender.com/ready
```

`/health` deve retornar `200`. `/ready` retorna `200` somente quando banco, S3 e env estiverem corretos.

## 6. Primeiro Admin

Abra:

```txt
https://sua-api.onrender.com/web/login
```

Crie o administrador inicial. Depois disso, use o painel normalmente.
