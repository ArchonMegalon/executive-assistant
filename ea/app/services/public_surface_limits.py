from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.services.public_request import trust_forwarded_ip


_RATE_DB_LOCK = threading.Lock()
_RATE_BACKEND_CACHE: str | None = None


def public_surface_rate_db_path() -> Path:
    explicit = str(os.getenv("EA_PUBLIC_SURFACE_RATE_DB") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    artifacts_dir = Path(str(os.getenv("EA_ARTIFACTS_DIR") or "/data/artifacts")).expanduser()
    return artifacts_dir / "public_surface_rate_limits.sqlite3"


def _safe_scope_token(value: object, fallback: str = "anon") -> str:
    normalized = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_", ":"})
    return normalized[:120] or fallback


def public_surface_client_key(
    *,
    headers: Mapping[str, object] | None = None,
    client_host: str = "",
    scope_hint: str = "",
) -> str:
    scope = _safe_scope_token(scope_hint, "")
    if scope:
        return scope
    headers = headers or {}
    forwarded = ""
    if trust_forwarded_ip():
        forwarded = str(headers.get("cf-connecting-ip") or headers.get("x-forwarded-for") or "").strip()
    ip = forwarded.split(",", 1)[0].strip() if forwarded else str(client_host or "").strip()
    return _safe_scope_token(f"ip:{ip}", "ip:unknown")


def public_surface_rate_backend() -> str:
    global _RATE_BACKEND_CACHE
    if _RATE_BACKEND_CACHE:
        return _RATE_BACKEND_CACHE
    configured = str(os.getenv("EA_PUBLIC_MEMORIAL_RATE_BACKEND") or "").strip().lower()
    if configured == "redis":
        try:
            import importlib.util

            if importlib.util.find_spec("redis") is not None and str(os.getenv("EA_PUBLIC_MEMORIAL_REDIS_URL") or "").strip():
                _RATE_BACKEND_CACHE = "redis"
                return _RATE_BACKEND_CACHE
        except Exception:
            pass
    _RATE_BACKEND_CACHE = "sqlite"
    return _RATE_BACKEND_CACHE


@lru_cache(maxsize=1)
def public_surface_redis_client():
    redis_url = str(os.getenv("EA_PUBLIC_MEMORIAL_REDIS_URL") or "").strip()
    if not redis_url:
        return None
    try:
        import redis

        return redis.Redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


def enforce_public_surface_rate_limit(*, bucket: str, client_key: str, limit: int, window_seconds: int) -> None:
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - float(window_seconds)
    bucket_key = f"{bucket}:{client_key}"
    backend = public_surface_rate_backend()
    if backend == "redis" and _enforce_public_surface_rate_limit_redis(bucket_key=bucket_key, now=now, cutoff=cutoff, limit=limit, window_seconds=window_seconds):
        return
    rate_db = public_surface_rate_db_path()
    try:
        rate_db.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        rate_db = Path(tempfile.gettempdir()) / "ea-public-surface-rate-limits.sqlite3"
        rate_db.parent.mkdir(parents=True, exist_ok=True)
    with _RATE_DB_LOCK:
        connection = sqlite3.connect(str(rate_db), timeout=5)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS public_surface_rate_events (bucket_key TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_public_surface_rate_events_bucket_time ON public_surface_rate_events(bucket_key, created_at)")
            connection.execute("DELETE FROM public_surface_rate_events WHERE created_at < ?", (cutoff,))
            row = connection.execute(
                "SELECT COUNT(*) FROM public_surface_rate_events WHERE bucket_key = ? AND created_at >= ?",
                (bucket_key, cutoff),
            ).fetchone()
            count = int(row[0] if row else 0)
            if count >= limit:
                raise RuntimeError("public_rate_limited")
            connection.execute(
                "INSERT INTO public_surface_rate_events(bucket_key, created_at) VALUES(?, ?)",
                (bucket_key, now),
            )
            connection.commit()
        finally:
            connection.close()


def _enforce_public_surface_rate_limit_redis(
    *,
    bucket_key: str,
    now: float,
    cutoff: float,
    limit: int,
    window_seconds: int,
) -> bool:
    client = public_surface_redis_client()
    if client is None:
        return False
    redis_key = f"public-rate:{bucket_key}"
    member = f"{now}:{uuid.uuid4().hex}"
    try:
        pipeline = client.pipeline()
        pipeline.zremrangebyscore(redis_key, 0, cutoff)
        pipeline.zcard(redis_key)
        pipeline.expire(redis_key, max(window_seconds * 2, 120))
        _, count, _ = pipeline.execute()
        if int(count or 0) >= limit:
            raise RuntimeError("public_rate_limited")
        pipeline = client.pipeline()
        pipeline.zadd(redis_key, {member: now})
        pipeline.expire(redis_key, max(window_seconds * 2, 120))
        pipeline.execute()
        return True
    except RuntimeError:
        raise
    except Exception:
        return False
