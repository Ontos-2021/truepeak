import os
import threading
import time
import uuid


class TokenStore:
    def __init__(self, directory, ttl_seconds=600):
        self.directory = directory
        self.ttl = ttl_seconds
        self._entries = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sweep, daemon=True)
        self._thread.start()

    def _sweep(self):
        while not self._stop.wait(30):
            self._cleanup()

    def _cleanup(self):
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._entries.items() if exp < now]
            for key in expired:
                path = self._entries.pop(key)[0]
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

    def add(self, path):
        token = uuid.uuid4().hex
        with self._lock:
            self._entries[token] = (path, time.time() + self.ttl)
        return token

    def take(self, token):
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry is None:
            return None
        return entry[0]

    def shutdown(self):
        self._stop.set()
        self._cleanup()
