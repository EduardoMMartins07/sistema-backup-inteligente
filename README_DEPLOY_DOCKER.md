# Deploy com Docker em VPS

## Desenvolvimento Local

1. Copie `.env.example` para `.env`.
2. Ajuste `JWT_SECRET`, variaveis AWS e `CORS_ORIGIN`.
3. Suba os containers:

```bash
docker compose up -d --build
```

O compose sobe:

- PostgreSQL 16 em `localhost:5432`;
- API FastAPI em `http://localhost:8000`.

## VPS Linux

1. Instale Docker e Docker Compose.
2. Clone o repositorio.
3. Crie `.env` com variaveis reais.
4. Execute:

```bash
docker compose up -d --build
docker compose logs -f api
```

## Migrations

O compose executa:

```bash
python -m api.manage migrate
```

antes de iniciar o Uvicorn. Para rodar manualmente:

```bash
docker compose exec api python -m api.manage migrate
```

## HTTPS com Nginx e Certbot

Em VPS, use Nginx como proxy reverso:

```nginx
server {
    server_name api.seudominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Ative HTTPS:

```bash
sudo certbot --nginx -d api.seudominio.com
```

Em producao, configure o agente com:

```txt
API_URL=https://api.seudominio.com
```

