import collections
import logging
import threading
from datetime import datetime


class MemoryLogHandler(logging.Handler):
    """Thread-safe in-memory ring buffer of recent log records."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._lock = threading.Lock()
        self._seq = 0
        self._records: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._seq += 1
                self._records.append({
                    "seq": self._seq,
                    "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                })
        except Exception:
            self.handleError(record)

    def get_since(self, seq: int) -> list:
        """Return all records whose seq number is greater than *seq*."""
        with self._lock:
            return [r for r in self._records if r["seq"] > seq]

    def get_all(self) -> list:
        with self._lock:
            return list(self._records)
