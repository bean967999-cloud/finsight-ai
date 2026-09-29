"""Fail closed before importing database/application modules; never echo values."""

from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate_runtime_environment(values, *, check_mounts=True):
    errors = []
    required = (
        "APP_ENV", "APP_HOST", "APP_PORT", "AUTH_JWT_SECRET", "AUTH_TOKEN_MINUTES",
        "DATABASE_URL", "REDIS_URL", "MILVUS_URI", "MILVUS_COLLECTION",
        "MINERU_API_URL", "EMBEDDING_DIMENSION", "OBJECT_STORAGE_ROOT",
        "EVALUATION_RUNS_ROOT", "FINSIGHT_BGE_M3_PATH", "FINSIGHT_BGE_MODEL_PATH",
        "FINSIGHT_RERANKER_PATH", "FINSIGHT_RERANKER_VERSION",
        "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
    )
    for key in required:
        value = values.get(key, "")
        if not value.strip() or any(
            term in value.upper() for term in ("CHANGE_ME", "REPLACE_ME", "${")
        ):
            errors.append(f"{key}: required explicit deployment value")
    for key, expected in (("APP_ENV", "deploy"), ("APP_HOST", "0.0.0.0"),
                          ("HF_HUB_OFFLINE", "1"), ("TRANSFORMERS_OFFLINE", "1"),
                          ("EMBEDDING_DIMENSION", "1024")):
        if values.get(key) != expected:
            errors.append(f"{key}: deployment policy mismatch")
    for key, lower, upper in (("APP_PORT", 1024, 65535), ("AUTH_TOKEN_MINUTES", 1, 120)):
        value = values.get(key, "")
        if not value.isdecimal() or not lower <= int(value) <= upper:
            errors.append(f"{key}: invalid range")
    if len(values.get("AUTH_JWT_SECRET", "").encode()) < 32:
        errors.append("AUTH_JWT_SECRET: requires at least 32 bytes")
    for key, scheme, host, port in (
        ("DATABASE_URL", "postgresql+psycopg", "postgres", 5432),
        ("REDIS_URL", "redis", "redis", 6379),
        ("MILVUS_URI", "http", "milvus", 19530),
        ("MINERU_API_URL", "http", "mineru", 8000),
    ):
        try:
            url = urlsplit(values.get(key, ""))
            if (url.scheme, url.hostname, url.port) != (scheme, host, port):
                errors.append(f"{key}: expected internal Compose endpoint")
            if key == "DATABASE_URL" and (
                not url.username or not url.password or url.path != "/finsight"
                or unquote(url.password).casefold() in {"finsight", "postgres", "password"}
            ):
                errors.append("DATABASE_URL: missing identity or unsafe default")
        except ValueError:
            errors.append(f"{key}: malformed endpoint")
    model_keys = ("FINSIGHT_BGE_M3_PATH", "FINSIGHT_RERANKER_PATH")
    paths = (*model_keys, "FINSIGHT_BGE_MODEL_PATH", "OBJECT_STORAGE_ROOT", "EVALUATION_RUNS_ROOT")
    for key in paths:
        value = values.get(key, "")
        path = Path(value)
        if not path.is_absolute() or path == Path(path.anchor) or ".." in path.parts:
            errors.append(f"{key}: requires bounded absolute path")
        elif check_mounts and not path.is_dir():
            errors.append(f"{key}: required directory not mounted")
    if values.get("FINSIGHT_BGE_M3_PATH") != values.get("FINSIGHT_BGE_MODEL_PATH"):
        errors.append("MODEL_PATHS: API and worker mismatch")
    if values.get("OBJECT_STORAGE_ROOT") == values.get("EVALUATION_RUNS_ROOT"):
        errors.append("STORAGE_PATHS: roots must be separate")
    if check_mounts:
        for key in model_keys:
            path = Path(values.get(key, ""))
            if not (path / "config.json").is_file() or not any(
                (path / name).is_file()
                for name in ("pytorch_model.bin", "model.safetensors", "model.safetensors.index.json",
                             "pytorch_model.bin.index.json")
            ):
                errors.append(f"{key}: model configuration or weight manifest missing")
    return errors


def require_runtime_environment(values):
    errors = validate_runtime_environment(values)
    if errors:
        raise RuntimeError("Deployment preflight refused: " + "; ".join(errors))
