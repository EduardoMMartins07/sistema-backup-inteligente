import hashlib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_PATH = os.path.join(PROJECT_ROOT, "config", "llm_classification_cache.json")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT_SECONDS = 20
CACHE_LIMIT = 1000
_ENV_FILE_LOADED = False

PRIORITY_LOW = "baixa"
PRIORITY_MEDIUM = "media"
PRIORITY_HIGH = "alta"
VALID_PRIORITIES = {PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH}
PRIORITY_LEVEL = {
    PRIORITY_LOW: 1,
    PRIORITY_MEDIUM: 2,
    PRIORITY_HIGH: 3,
}
PRIORITY_BASE_SCORE = {
    PRIORITY_LOW: 25,
    PRIORITY_MEDIUM: 55,
    PRIORITY_HIGH: 85,
}
BACKUP_POLICIES = {
    PRIORITY_LOW: "backup_semanal_7_dias",
    PRIORITY_MEDIUM: "backup_a_cada_2_dias",
    PRIORITY_HIGH: "backup_inicio_do_dia_e_a_cada_4_horas",
}

HIGH_VALUE_EXTENSIONS = {
    "doc",
    "docx",
    "odt",
    "pdf",
    "txt",
    "rtf",
    "xls",
    "xlsx",
    "ods",
    "csv",
    "ppt",
    "pptx",
    "odp",
    "db",
    "sqlite",
    "sqlite3",
    "sql",
    "bak",
    "backup",
    "zip",
    "rar",
    "7z",
    "py",
    "js",
    "ts",
    "java",
    "cpp",
    "c",
    "cs",
    "php",
    "html",
    "css",
    "json",
    "xml",
    "yaml",
    "yml",
    "ini",
    "conf",
    "config",
    "env",
    "pem",
    "key",
    "pfx",
    "crt",
    "cer",
}

SYSTEM_PROGRAM_EXTENSIONS = {
    "env",
    "db",
    "sqlite",
    "sqlite3",
    "sql",
    "json",
    "xml",
    "yaml",
    "yml",
    "ini",
    "conf",
    "config",
    "py",
    "js",
    "ts",
    "java",
    "cpp",
    "c",
    "cs",
    "php",
    "bat",
    "ps1",
    "sh",
    "pem",
    "key",
    "pfx",
}

LOW_VALUE_EXTENSIONS = {
    "tmp",
    "temp",
    "cache",
    "log",
    "old",
    "dmp",
    "part",
    "crdownload",
}

IMPORTANT_NAME_KEYWORDS = {
    "backup",
    "banco",
    "cliente",
    "clientes",
    "config",
    "contrato",
    "contratos",
    "credencial",
    "database",
    "documento",
    "empresa",
    "financeiro",
    "fiscal",
    "importante",
    "nota",
    "oramento",
    "orcamento",
    "pagamento",
    "projeto",
    "recibo",
    "relatorio",
    "senha",
    "tcc",
}

IMPORTANT_CONTEXT_KEYWORDS = {
    "area de trabalho",
    "backup",
    "banco",
    "clientes",
    "codigo",
    "contratos",
    "database",
    "db",
    "desktop",
    "documents",
    "documentos",
    "empresa",
    "financeiro",
    "projetos",
    "projects",
    "relatorios",
    "source",
    "src",
    "trabalho",
}

LOW_CONTEXT_KEYWORDS = {
    ".git",
    ".venv",
    "__pycache__",
    "cache",
    "logs",
    "node_modules",
    "temp",
    "tmp",
    "venv",
}


def load_json(path, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return default

    return data if isinstance(data, type(default)) else default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def load_local_env_file(path=ENV_PATH):
    global _ENV_FILE_LOADED

    if _ENV_FILE_LOADED:
        return

    _ENV_FILE_LOADED = True

    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()

            if key.startswith("export "):
                key = key.replace("export ", "", 1).strip()

            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def parse_bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()

    if normalized in {"1", "true", "sim", "yes", "on", "ativo"}:
        return True

    if normalized in {"0", "false", "nao", "no", "off", "inativo"}:
        return False

    return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, int(round(value))))


def normalize_token(value):
    value = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return normalized.strip().lower()


def normalize_extension(extension):
    return normalize_token(extension).lstrip(".")


def normalize_priority(value, default=PRIORITY_LOW):
    normalized = normalize_token(value)

    if normalized in {"media", "medio", "medica"}:
        return PRIORITY_MEDIUM

    if normalized in {"alta", "alto"}:
        return PRIORITY_HIGH

    if normalized in {"baixa", "baixo"}:
        return PRIORITY_LOW

    return default


def extract_context_parts(path):
    if not path:
        return []

    normalized = os.path.normpath(str(path))
    parts = []
    current = os.path.dirname(normalized)

    for _ in range(5):
        name = os.path.basename(current)

        if not name:
            break

        parts.insert(0, name)
        parent = os.path.dirname(current)

        if parent == current:
            break

        current = parent

    return parts


def contains_keyword(text, keywords):
    normalized_text = normalize_token(text)

    for keyword in keywords:
        if normalize_token(keyword) in normalized_text:
            return True

    return False


def format_reason_list(reasons, limit=6):
    seen = set()
    unique_reasons = []

    for reason in reasons:
        reason = str(reason).strip()

        if not reason:
            continue

        reason_key = normalize_token(reason)

        if reason_key in seen:
            continue

        unique_reasons.append(reason)
        seen.add(reason_key)

        if len(unique_reasons) >= limit:
            break

    return unique_reasons


def build_decision_context(file_data):
    source_path = file_data.get("source_path", "")
    context_parts = file_data.get("directory_context") or extract_context_parts(source_path)

    if isinstance(context_parts, str):
        context_parts = [
            part.strip()
            for part in re.split(r"[\\/|>]+", context_parts)
            if part.strip()
        ]

    context_text = " ".join(context_parts)
    name = file_data.get("name", "")
    extension = normalize_extension(file_data.get("extension", ""))
    modified_count = safe_int(file_data.get("modified_count"))
    accessed_count = safe_int(file_data.get("accessed_count"))
    days_since_modified = safe_int(file_data.get("days_since_modified"), 9999)

    return {
        "name": name,
        "extension": extension,
        "source_path": source_path,
        "directory_context": context_parts,
        "context_text": context_text,
        "modified_count": modified_count,
        "accessed_count": accessed_count,
        "days_since_modified": days_since_modified,
    }


def classify_with_rules(file_data):
    context = build_decision_context(file_data)
    extension = context["extension"]
    name = context["name"]
    context_text = context["context_text"]
    modified_count = context["modified_count"]
    accessed_count = context["accessed_count"]
    days_since_modified = context["days_since_modified"]

    decisions = {
        "frequent_modifications": modified_count >= 2 or days_since_modified <= 2,
        "high_value_extension": extension in HIGH_VALUE_EXTENSIONS,
        "system_or_program_extension": extension in SYSTEM_PROGRAM_EXTENSIONS,
        "frequent_access": accessed_count >= 2,
        "important_name": contains_keyword(name, IMPORTANT_NAME_KEYWORDS),
        "important_context": contains_keyword(context_text, IMPORTANT_CONTEXT_KEYWORDS),
        "low_value_extension": extension in LOW_VALUE_EXTENSIONS,
        "low_value_context": contains_keyword(context_text, LOW_CONTEXT_KEYWORDS),
    }

    score = 10
    reasons = []

    if decisions["frequent_modifications"]:
        score += 18
        reasons.append("arquivo modificado recentemente ou varias vezes")

    if decisions["high_value_extension"]:
        score += 18
        reasons.append("extensao com valor potencial para backup")

    if decisions["system_or_program_extension"]:
        score += 20
        reasons.append("tipo/extensao relevante para sistema ou programa")

    if decisions["frequent_access"]:
        score += 14
        reasons.append("arquivo acessado varias vezes entre varreduras")

    if decisions["important_name"]:
        score += 24
        reasons.append("nome indica documento, projeto, cliente ou dado sensivel")

    if decisions["important_context"]:
        score += 18
        reasons.append("diretorio indica contexto importante")

    if safe_int(file_data.get("important_keyword")) == 1:
        score += 10
        reasons.append("palavra-chave importante detectada pelo scanner")

    if safe_int(file_data.get("is_duplicate")) == 1:
        score -= 6
        reasons.append("conteudo duplicado encontrado por hash")

    if decisions["low_value_extension"]:
        score -= 18
        reasons.append("extensao comum em arquivo temporario ou descartavel")

    if decisions["low_value_context"]:
        score -= 35
        reasons.append("diretorio parece cache, ambiente virtual ou temporario")

    score = clamp(score)

    if score >= 70:
        priority = PRIORITY_HIGH
    elif score >= 40:
        priority = PRIORITY_MEDIUM
    else:
        priority = PRIORITY_LOW

    if not reasons:
        reasons.append("sem sinais fortes de importancia nos metadados")

    return {
        "priority": priority,
        "priority_score": score,
        "confidence": round(0.58 + (score / 250), 2),
        "reasons": format_reason_list(reasons),
        "decisions": decisions,
        "classification_source": "rules",
        "llm_model": "",
        "llm_error": "",
    }


def get_api_key():
    load_local_env_file()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def get_gemini_model(config=None):
    load_local_env_file()
    config = config or {}
    return (
        os.environ.get("GEMINI_MODEL")
        or config.get("gemini_model")
        or DEFAULT_GEMINI_MODEL
    )


def get_timeout_seconds(config=None):
    load_local_env_file()
    config = config or {}
    return safe_int(
        os.environ.get("GEMINI_TIMEOUT_SECONDS")
        or config.get("llm_request_timeout_seconds"),
        DEFAULT_TIMEOUT_SECONDS
    )


def is_llm_enabled(config=None):
    load_local_env_file()
    config = config or {}
    env_value = os.environ.get("SMARTBACKUP_LLM_ENABLED")

    if env_value is not None:
        return parse_bool(env_value, default=False) and bool(get_api_key())

    config_enabled = parse_bool(
        config.get("llm_classification_enabled"),
        default=True
    )
    return config_enabled and bool(get_api_key())


def is_cache_enabled(config=None):
    config = config or {}
    return parse_bool(config.get("llm_cache_enabled"), default=True)


def build_cache_key(file_data, model):
    payload = {
        "model": model,
        "name": file_data.get("name", ""),
        "extension": file_data.get("extension", ""),
        "source_path": file_data.get("source_path", ""),
        "size_kb": round(safe_float(file_data.get("size_kb")), 3),
        "days_since_modified": safe_int(file_data.get("days_since_modified")),
        "modified_count": safe_int(file_data.get("modified_count")),
        "accessed_count": safe_int(file_data.get("accessed_count")),
        "file_hash": file_data.get("file_hash", ""),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def trim_cache(cache):
    if len(cache) <= CACHE_LIMIT:
        return cache

    ordered_items = sorted(
        cache.items(),
        key=lambda item: item[1].get("created_at", "")
    )
    return dict(ordered_items[-CACHE_LIMIT:])


def build_prompt(file_data, rule_result):
    metadata = {
        "nome": file_data.get("name", ""),
        "extensao": file_data.get("extension", ""),
        "tipo": file_data.get("type", ""),
        "tamanho_kb": safe_float(file_data.get("size_kb")),
        "dias_desde_modificacao": safe_int(file_data.get("days_since_modified")),
        "quantidade_modificacoes_observadas": safe_int(file_data.get("modified_count")),
        "quantidade_acessos_observados": safe_int(file_data.get("accessed_count")),
        "diretorio_contexto": file_data.get("directory_context", ""),
        "duplicado_por_hash": bool(safe_int(file_data.get("is_duplicate"))),
        "politica_regra_local": rule_result.get("priority", PRIORITY_LOW),
        "pontuacao_regra_local": rule_result.get("priority_score", 0),
        "decisoes_regra_local": rule_result.get("decisions", {}),
    }

    return (
        "Voce classifica a importancia de arquivos para um sistema de backup.\n"
        "Use somente os metadados abaixo. Nao presuma o conteudo real do arquivo.\n"
        "Siga esta arvore de decisao: quantidade de modificacoes, tipo/extensao, "
        "quantidade de acessos, nome do arquivo e diretorio/contexto. "
        "Sinais positivos aumentam a prioridade; sinais temporarios/cache/log "
        "reduzem a prioridade.\n\n"
        "Politicas de prioridade:\n"
        "- baixa: backup uma vez por semana.\n"
        "- media: backup a cada 2 dias.\n"
        "- alta: backup no primeiro inicio do programa no dia e a cada 4 horas "
        "com o programa aberto em segundo plano.\n\n"
        "Responda somente com JSON valido neste formato:\n"
        "{"
        "\"prioridade\":\"baixa|media|alta\","
        "\"pontuacao\":0,"
        "\"confianca\":0.0,"
        "\"motivos\":[\"motivo curto\"],"
        "\"decisoes\":{"
        "\"modificacoes_relevantes\":false,"
        "\"tipo_critico\":false,"
        "\"acessos_relevantes\":false,"
        "\"nome_critico\":false,"
        "\"contexto_critico\":false"
        "}"
        "}\n\n"
        f"Metadados:\n{json.dumps(metadata, ensure_ascii=False, indent=2)}"
    )


def parse_json_text(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    return json.loads(text)


def request_gemini_classification(file_data, rule_result, config=None):
    config = config or {}
    api_key = get_api_key()

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY nao configurada.")

    model = get_gemini_model(config)
    timeout_seconds = get_timeout_seconds(config)
    prompt = build_prompt(file_data, rule_result)
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API retornou HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Falha de conexao com Gemini API: {error.reason}") from error

    try:
        text = response_data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Resposta da Gemini API sem texto classificavel.") from error

    result = parse_json_text(text)

    if not isinstance(result, dict):
        raise RuntimeError("Resposta da Gemini API nao retornou objeto JSON.")

    return result


def normalize_llm_result(raw_result):
    priority = normalize_priority(
        raw_result.get("prioridade")
        or raw_result.get("priority")
        or raw_result.get("prioridade_final"),
        default=PRIORITY_LOW
    )
    score = clamp(
        raw_result.get("pontuacao")
        or raw_result.get("score")
        or PRIORITY_BASE_SCORE[priority]
    )
    confidence = safe_float(
        raw_result.get("confianca")
        or raw_result.get("confidence"),
        0.65
    )

    if confidence > 1:
        confidence = confidence / 100

    reasons = raw_result.get("motivos") or raw_result.get("reasons") or []

    if isinstance(reasons, str):
        reasons = [reasons]

    decisions = raw_result.get("decisoes") or raw_result.get("decisions") or {}

    if not isinstance(decisions, dict):
        decisions = {}

    return {
        "priority": priority,
        "priority_score": score,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "reasons": format_reason_list(reasons),
        "decisions": decisions,
    }


def merge_rule_and_llm_results(rule_result, llm_result, model):
    rule_priority = rule_result.get("priority", PRIORITY_LOW)
    llm_priority = llm_result.get("priority", PRIORITY_LOW)
    llm_confidence = safe_float(llm_result.get("confidence"), 0.0)
    rule_score = safe_int(rule_result.get("priority_score"))
    llm_score = safe_int(llm_result.get("priority_score"))

    if llm_confidence < 0.55 and rule_priority != llm_priority:
        final_priority = rule_priority
        final_score = rule_score
    else:
        final_level = max(
            PRIORITY_LEVEL.get(rule_priority, 1),
            PRIORITY_LEVEL.get(llm_priority, 1)
        )
        final_priority = next(
            priority
            for priority, level in PRIORITY_LEVEL.items()
            if level == final_level
        )
        final_score = max(
            rule_score,
            llm_score,
            PRIORITY_BASE_SCORE[final_priority]
        )

    reasons = format_reason_list(
        list(rule_result.get("reasons", []))
        + list(llm_result.get("reasons", []))
    )
    decisions = dict(rule_result.get("decisions", {}))

    for key, value in llm_result.get("decisions", {}).items():
        decisions[f"llm_{key}"] = value

    return {
        "priority": final_priority,
        "priority_score": clamp(final_score),
        "confidence": round(
            max(safe_float(rule_result.get("confidence"), 0.0), llm_confidence),
            2
        ),
        "reasons": reasons,
        "decisions": decisions,
        "classification_source": "gemini_api",
        "llm_model": model,
        "llm_error": "",
    }


def finalize_result(result):
    priority = normalize_priority(result.get("priority"), default=PRIORITY_LOW)
    reasons = format_reason_list(result.get("reasons", []))

    result["priority"] = priority
    result["priority_score"] = clamp(result.get("priority_score", 0))
    result["priority_reason"] = "; ".join(reasons)
    result["important"] = 1 if priority in {PRIORITY_MEDIUM, PRIORITY_HIGH} else 0
    result["backup_policy"] = BACKUP_POLICIES[priority]
    result["llm_confidence"] = safe_float(result.get("confidence"), 0.0)
    result["decision_tree"] = json.dumps(
        result.get("decisions", {}),
        ensure_ascii=False,
        sort_keys=True
    )
    return result


def classify_file_importance(file_data, config=None):
    config = config or {}
    rule_result = classify_with_rules(file_data)
    rule_score = rule_result.get("priority_score", 0)

    # Se as regras ja classificaram como baixa prioridade com score < 30,
    # pula a chamada LLM: a chance de upgrade e minima e nao justifica o custo.
    if not is_llm_enabled(config):
        return finalize_result(rule_result)

    if rule_score < 30 and rule_result.get("priority") == PRIORITY_LOW:
        rules_only = dict(rule_result)
        rules_only["llm_error"] = ""
        return finalize_result(rules_only)

    model = get_gemini_model(config)
    cache_key = build_cache_key(file_data, model)
    cache = load_json(CACHE_PATH, {}) if is_cache_enabled(config) else {}
    cached_entry = cache.get(cache_key)

    if cached_entry and isinstance(cached_entry.get("result"), dict):
        cached_result = dict(cached_entry["result"])
        cached_result["classification_source"] = "gemini_cache"
        return finalize_result(cached_result)

    try:
        raw_llm_result = request_gemini_classification(file_data, rule_result, config)
        llm_result = normalize_llm_result(raw_llm_result)
        final_result = merge_rule_and_llm_results(rule_result, llm_result, model)
    except Exception as error:
        fallback_result = dict(rule_result)
        fallback_result["classification_source"] = "rules_fallback"
        fallback_result["llm_error"] = str(error)
        return finalize_result(fallback_result)

    final_result = finalize_result(final_result)

    if is_cache_enabled(config):
        cache[cache_key] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "result": final_result,
        }
        save_json(CACHE_PATH, trim_cache(cache))

    return final_result
