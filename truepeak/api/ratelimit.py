import threading
import time
from collections import defaultdict

from flask import request


class RateLimiter:
    def __init__(self, max_calls, per_seconds, enabled_getter=None):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.enabled_getter = enabled_getter
        self.calls = defaultdict(list)
        self._lock = threading.Lock()
        self._check_count = 0

    def allow(self):
        if self.enabled_getter is not None and not self.enabled_getter():
            return True
        ip = request.remote_addr or "unknown"
        now = time.time()
        with self._lock:
            self.calls[ip] = [c for c in self.calls[ip] if c > now - self.per_seconds]
            if len(self.calls[ip]) >= self.max_calls:
                return False
            self.calls[ip].append(now)
            self._check_count += 1
            if self._check_count >= 512:
                self._check_count = 0
                for key in [k for k, v in self.calls.items() if not v]:
                    del self.calls[key]
            return True
