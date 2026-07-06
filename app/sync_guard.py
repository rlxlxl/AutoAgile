import threading
import time


class EchoGuard:
    """In-memory one-shot guard that suppresses webhook echo loops.

    After writing a checklist state to a system we ``remember`` the resulting
    state hash. The webhook that write triggers arrives shortly after carrying
    the same hash; ``seen`` matches and pops it so the echo is ignored exactly
    once. Entries expire after ``ttl`` seconds to avoid unbounded growth.
    """

    def __init__(self, ttl: float = 120.0):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, str], float] = {}

    @staticmethod
    def _key(system: str, key: str, state_hash: str) -> tuple[str, str, str]:
        return (system, str(key), state_hash)

    def _purge(self, now: float) -> None:
        expired = [k for k, ts in self._entries.items() if now - ts > self.ttl]
        for k in expired:
            self._entries.pop(k, None)

    def remember(self, system: str, key: str, state_hash: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._entries[self._key(system, key, state_hash)] = now

    def seen(self, system: str, key: str, state_hash: str) -> bool:
        now = time.monotonic()
        entry_key = self._key(system, key, state_hash)
        with self._lock:
            self._purge(now)
            if entry_key in self._entries:
                self._entries.pop(entry_key, None)
                return True
            return False


guard = EchoGuard()
