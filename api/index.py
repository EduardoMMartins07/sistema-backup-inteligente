"""Ponto de entrada para o runtime serverless do Vercel.

O Vercel importa este arquivo e usa a variável `app` (ASGI) para
rotear todas as requisições definidas em `vercel.json`.
"""

from api.app import app

# A importação acima já dispara o lifespan da aplicação FastAPI,
# que executa init_db() (criação de tabelas / migrations) na
# inicialização. Como as operações usam CREATE TABLE IF NOT EXISTS,
# são idempotentes e seguras para execução repetida em cold starts.
