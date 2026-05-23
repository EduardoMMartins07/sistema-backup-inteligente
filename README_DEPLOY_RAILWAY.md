# Deploy no Railway

## Passos

1. Crie um projeto no Railway.
2. Conecte o repositorio GitHub.
3. Adicione o plugin PostgreSQL.
4. Configure `DATABASE_URL` usando a variavel gerada pelo Railway.
5. Configure as variaveis AWS, JWT, CORS e upload.
6. Defina o start command:

```bash
python -m api.manage migrate && python -m uvicorn api.app:app --host 0.0.0.0 --port $PORT
```

## Variaveis Minimas

```txt
SMARTBACKUP_ENV=production
PORT=${{PORT}}
API_BASE_URL=https://seu-servico.up.railway.app
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET=valor-longo-e-aleatorio
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=sa-east-1
AWS_S3_BUCKET=...
CORS_ORIGIN=https://seu-servico.up.railway.app
MAX_UPLOAD_SIZE_MB=500
```

## Testes

```bash
curl https://seu-servico.up.railway.app/health
curl https://seu-servico.up.railway.app/ready
```

Se `/ready` retornar `503`, confira `DATABASE_URL` e as variaveis AWS.

