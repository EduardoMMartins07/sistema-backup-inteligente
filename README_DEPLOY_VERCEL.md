# Deploy no Vercel (com Supabase + Cloudflare R2)

## ⚠️ Requisitos obrigatorios

| Recurso    | Por que                                    | Opcao que voce ja usa |
| ---------- | ------------------------------------------ | --------------------- |
| PostgreSQL | Vercel nao tem filesystem persistente      | **Supabase**          |
| Bucket S3  | Armazenamento de backups efemero no Vercel | Cloudflare R2         |

> **SQLite nao funciona no Vercel.** Toda vez que a funcao "esfria", os dados seriam perdidos.
> Como voce ja usa **Supabase** (PostgreSQL) e tem suporte a S3, a migracao e tranquila.

---

## 1. Preparar o repositorio

1. Crie um repositorio no **GitHub** e suba o projeto.
2. Confirme que `.env` **nao** foi commitado (adicione ao `.gitignore` se necessario).
3. Os arquivos criados para o Vercel sao:
   - `vercel.json` — configuracao do deploy
   - `api/index.py` — ponto de entrada serverless
   - `requirements-vercel.txt` — dependencias apenas da API (sem GUI)

---

## 2. Obter a string do Supabase (voce ja tem)

1. Acesse [supabase.com](https://supabase.com) → **Project Settings → Database**.
2. Em **Connection string**, selecione a aba **URI**.
3. Copie a string no formato:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:5432/postgres
   ```

> 💡 Dica: se preferir usar o **pooler** (PgBouncer) do Supabase para ambientes
> serverless, use a porta `6543` em vez de `5432`:
>
> ```
> postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:6543/postgres
> ```

---

## 3. Criar o bucket S3 (Cloudflare R2 — gratuito)

1. Acesse [cloudflare.com](https://cloudflare.com) → R2.
2. Crie um bucket (ex: `smartbackup-files`).
3. Gere uma **credencial de API** com permissao de leitura e escrita.
4. Separe os valores:
   ```
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_REGION=auto
   AWS_S3_BUCKET=smartbackup-files
   AWS_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
   ```

---

## 4. Fazer o deploy no Vercel

### Opcao A — Via CLI (recomendado)

```bash
# Instalar a Vercel CLI
npm install -g vercel

# Logar (abre o browser)
vercel login

# Deploy a partir da raiz do projeto
vercel --prod
```

### Opcao B — Via dashboard (vercel.com)

1. Acesse [vercel.com](https://vercel.com) e clique em **Add New → Project**.
2. Importe o repositorio do GitHub.
3. **Nao altere** o Framework Preset (deixe como `Other`).
4. Em **Build & Output Settings**:
   - **Build Command**: deixe vazio
   - **Output Directory**: deixe vazio
   - **Install Command**: `pip install -r requirements-vercel.txt`
5. Clique em **Deploy**.

---

## 5. Configurar variaveis de ambiente

No dashboard do Vercel (ou via CLI com `vercel env add`), configure:

| Variavel                          | Valor                                                |
| --------------------------------- | ---------------------------------------------------- |
| `SMARTBACKUP_ENV`                 | `production`                                         |
| `API_BASE_URL`                    | `https://seu-projeto.vercel.app`                     |
| `DATABASE_URL`                    | `postgresql://postgres:...` (string do **Supabase**) |
| `SMARTBACKUP_JWT_SECRET`          | `um-valor-longo-e-aleatorio-aqui`                    |
| `SMARTBACKUP_API_STORAGE_BACKEND` | `s3`                                                 |
| `AWS_ACCESS_KEY_ID`               | (credencial do R2)                                   |
| `AWS_SECRET_ACCESS_KEY`           | (credencial do R2)                                   |
| `AWS_REGION`                      | `auto`                                               |
| `AWS_S3_BUCKET`                   | `smartbackup-files`                                  |
| `AWS_ENDPOINT_URL`                | `https://<accountid>.r2.cloudflarestorage.com`       |
| `CORS_ORIGIN`                     | `https://seu-projeto.vercel.app`                     |
| `MAX_UPLOAD_SIZE_MB`              | `500`                                                |

> **Dica:** gere um JWT_SECRET forte com:
>
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(48))"
> ```

---

## 6. Migrations e primeiro acesso

As migrations rodam **automaticamente** na inicializacao da aplicacao (dentro do
lifespan do FastAPI). Nenhum comando extra e necessario.

Apos o deploy:

```bash
# Testar saude da API
curl https://seu-projeto.vercel.app/health

# Testar readiness (banco + S3 + env)
curl https://seu-projeto.vercel.app/ready
```

Se `/ready` retornar `503`, verifique as variaveis de ambiente no Vercel.

### Criar o primeiro administrador

Abra no navegador:

```
https://seu-projeto.vercel.app/web/login
```

Siga o fluxo de **Primeiro Acesso** para criar o admin inicial.

---

## 7. Limites do plano Hobby (gratuito)

| Recurso              | Limite                        |
| -------------------- | ----------------------------- |
| Duracao da funcao    | 10s (Hobby) / 60s (Pro)       |
| Memoria              | 1024 MB maxima                |
| Tamanho do upload    | 4.5 MB (Hobby) / ~50 MB (Pro) |
| Requests simultaneos | 1000                          |
| Cold starts          | Sim (alguns segundos)         |

> Para uploads maiores, considere usar **presigned URLs** do S3 (ja implementado
> no codigo) ou migrar para o plano Pro.

---

## 8. Diferencas entre Vercel e Render

| Caracteristica | Vercel (serverless)           | Render (Web Service)   |
| -------------- | ----------------------------- | ---------------------- |
| Modelo         | Funcoes efemeras (cold start) | Container sempre ativo |
| Filesystem     | Read-only (exceto /tmp)       | Persistente            |
| Upload direto  | Limitado a 4.5 MB (Hobby)     | Ilimitado (disco)      |
| Custo          | Gratuito (Hobby)              | Gratuito (pausa dorme) |
| Complexidade   | Media (banco externo + S3)    | Baixa                  |

Se o limite de upload for um problema, **Render** (ou Docker em VPS) pode ser
mais adequado.

---

## 9. Solucao de problemas

| Problema                           | Causa provavel                          | Solucao                                   |
| ---------------------------------- | --------------------------------------- | ----------------------------------------- |
| `/ready` retorna 503               | Variaveis de ambiente ausentes          | Confira todas as envs no Vercel dashboard |
| `500 Internal Server Error`        | Erro de import ou dependencia faltando  | Verifique `requirements-vercel.txt`       |
| Login falha / nao persiste         | DATABASE_URL apontando para SQLite      | Configure a URL do **Supabase**           |
| Upload retorna 413                 | Limite de tamanho do Vercel             | Use presigned URLs S3 ou plano Pro        |
| Static files (CSS/JS) nao carregam | Caminho relativo quebrado no serverless | Verifique `api/index.py` e `vercel.json`  |
