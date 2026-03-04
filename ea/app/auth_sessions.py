from __future__ import annotations

import json
import os
import threading
import time


class AuthSessionStore:
    def __init__(self, path: str = "/attachments/auth_sessions.json", ttl_sec: int = 900):
        self._lock = threading.Lock()
        self._path = str(path)
        self._ttl_sec = max(60, int(ttl_sec))

    def _read(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def set(self, chat_id: int, session: dict) -> None:
        key = str(int(chat_id))
        with self._lock:
            data = self._read()
            data[key] = dict(session or {})
            self._write(data)

    def get_and_clear(self, chat_id: int) -> dict | None:
        key = str(int(chat_id))
        with self._lock:
            data = self._read()
            if key not in data:
                return None
            sess = data.pop(key)
            self._write(data)
            try:
                ts = float((sess or {}).get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if ts > 0 and (time.time() - ts) <= self._ttl_sec:
                return sess
            return None

    def clear(self, chat_id: int) -> None:
        key = str(int(chat_id))
        with self._lock:
            data = self._read()
            if key in data:
                del data[key]
                self._write(data)
