from __future__ import annotations

import threading
import time


class SessionTracker:
    """Tracks the most-recent thread per authenticated user.

    This lets /v1/chat include short-term context without changing the /v1/chat request schema.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active_thread_by_user: dict[str, tuple[str, float]] = {}

    def set_active_thread(self, user_id: str, thread_id: str) -> None:
        if not user_id or not thread_id:
            return
        now = time.time()
        with self._lock:
            self._active_thread_by_user[user_id] = (thread_id, now)

    def get_active_thread(self, user_id: str) -> str | None:
        if not user_id:
            return None
        with self._lock:
            entry = self._active_thread_by_user.get(user_id)
        if not entry:
            return None
        thread_id, _ts = entry
        return thread_id


session_tracker = SessionTracker()
