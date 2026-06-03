"""Cache opcional com Redis para acelerar consultas frequentes da API.

Uso:
    from api.cache import cache_get, cache_set, cached

    # Decorator
    @cached(ttl=30)
    def minha_funcao(param):
        ...

    # Direto
    data = cache_get("minha_chave")
    if data is None:
        data = calcular(...)
        cache_set("minha_chave", data, ttl=30)
"""

import json
import os
import threading
from functools import wraps

# ─── Configuracao ──────────────────────────────────────────────

_REDIS_CLIENT = None
_REDIS_LOCK = threading.Lock()
_REDIS_ENABLED = False


def _redis_url():
    return os.environ.get("REDIS_URL", "").strip()


def is_redis_configured():
    return bool(_redis_url())


def get_redis_client():
    global _REDIS_CLIENT, _REDIS_ENABLED

    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    url = _redis_url()

    if not url:
        _REDIS_ENABLED = False
        return None

    with _REDIS_LOCK:
        if _REDIS_CLIENT is not None:
            return _REDIS_CLIENT

        try:
            import redis as redis_module

            _REDIS_CLIENT = redis_module.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            _REDIS_CLIENT.ping()
            _REDIS_ENABLED = True
        except Exception:
            _REDIS_CLIENT = None
            _REDIS_ENABLED = False

    return _REDIS_CLIENT


# ─── Operacoes basicas ─────────────────────────────────────────


def cache_get(key):
    """Retorna o valor do cache ou None."""
    client = get_redis_client()

    if client is None:
        return None

    try:
        value = client.get(key)

        if value is None:
            return None

        return json.loads(value)
    except Exception:
        return None


def cache_set(key, value, ttl=60):
    """Guarda um valor no cache com TTL em segundos."""
    client = get_redis_client()

    if client is None:
        return False

    try:
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        return True
    except Exception:
        return False


def cache_delete(key):
    """Remove uma chave do cache."""
    client = get_redis_client()

    if client is None:
        return False

    try:
        client.delete(key)
        return True
    except Exception:
        return False


def cache_delete_pattern(pattern):
    """Remove todas as chaves que correspondem a um padrao (ex: 'dashboard:*')."""
    client = get_redis_client()

    if client is None:
        return 0

    try:
        keys = client.keys(pattern)

        if keys:
            return client.delete(*keys)

        return 0
    except Exception:
        return 0


# ─── Decorator ─────────────────────────────────────────────────


def cached(ttl=60, key_prefix=None):
    """Decorator que cacheia o retorno da funcao em Redis.

    Args:
        ttl: Tempo de vida em segundos.
        key_prefix: Prefixo opcional para a chave (usa nome da funcao se omitido).

    Uso:
        @cached(ttl=30)
        def minha_func(param1, param2):
            ...
    """

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not is_redis_configured():
                return func(*args, **kwargs)

            prefix = key_prefix or func.__name__
            key_parts = [prefix]

            for arg in args:
                key_parts.append(str(arg))

            for k, v in sorted(kwargs.items()):
                if v is not None:
                    key_parts.append(f"{k}={v}")

            cache_key = ":".join(key_parts)
            cached_value = cache_get(cache_key)

            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)
            cache_set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorator


# ─── Utilitarios para o dominio ────────────────────────────────


def make_cache_key(*parts):
    """Constrói uma chave de cache padronizada."""
    return ":".join(str(p) for p in parts)


def invalidate_company_cache(company_id):
    """Invalida todo o cache de uma empresa (dashboard, listas, etc)."""
    return cache_delete_pattern(f"*:{company_id}:*")


def cached_dashboard(ttl=30):
    """Decorator especifico para cache do dashboard (prefixo 'dashboard')."""
    return cached(ttl=ttl, key_prefix="dashboard")
