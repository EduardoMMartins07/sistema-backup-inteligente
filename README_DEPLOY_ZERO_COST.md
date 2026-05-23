# Deploy Custo Zero

Este e o caminho mais equilibrado para o projeto no inicio:

- API: Render Free Web Service
- Banco: Neon PostgreSQL Free
- Arquivos: Cloudflare R2 (S3 compativel)

## Por que este combo

- O backend continua rodando como API Python tradicional.
- O banco fica persistente fora do ciclo de vida do container.
- Os arquivos de backup vao para um bucket compativel com S3.
- O custo inicial tende a ser menor do que concentrar tudo em um unico provedor.

## 1. Criar o banco no Neon

1. Crie um projeto no Neon.
2. Copie a `DATABASE_URL` com SSL.
3. Guarde a URL para configurar no Render.

Exemplo:

```text
DATABASE_URL=postgresql://usuario:senha@ep-xxxx.sa-east-1.aws.neon.tech/neondb?sslmode=require
```

## 2. Criar o bucket no Cloudflare R2

1. Crie um bucket no R2.
2. Gere uma credencial com permissao de leitura e escrita.
3. Separe estes valores:

```text
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=auto
AWS_S3_BUCKET=nome-do-bucket
AWS_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
```

## 3. Publicar a API no Render

O repositorio agora possui `render.yaml`, entao o fluxo mais simples e:

1. Suba o projeto para o GitHub.
2. No Render, crie um recurso via **Blueprint**.
3. Selecione este repositorio.
4. O Render vai ler `render.yaml` automaticamente.

Preencha os envs marcados como `sync: false`:

```text
API_BASE_URL=https://seu-servico.onrender.com
API_URL=https://seu-servico.onrender.com
DATABASE_URL=<url-do-neon>
AWS_ACCESS_KEY_ID=<r2-access-key>
AWS_SECRET_ACCESS_KEY=<r2-secret-key>
AWS_S3_BUCKET=<bucket-r2>
AWS_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
CORS_ORIGIN=https://seu-servico.onrender.com
```

O `JWT_SECRET` e gerado automaticamente pelo Blueprint.

## 4. Validar

Depois do deploy:

```bash
curl https://seu-servico.onrender.com/health
curl https://seu-servico.onrender.com/ready
```

- `/health` deve responder `200`
- `/ready` deve responder `200` quando banco, S3 e envs estiverem corretos

Depois disso, abra:

```text
https://seu-servico.onrender.com/web/login
```

e crie o primeiro admin da empresa.

## 5. Observacoes do plano gratis

- O Render Free pode dormir sem trafego.
- O Neon Free possui cotas de armazenamento e uso mensal.
- O R2 possui franquia gratuita, mas deve ser monitorado conforme o volume de upload e download.
- Para uma apresentacao de TCC ou homologacao, esse caminho costuma ser suficiente.
