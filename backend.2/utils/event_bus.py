import threading
import time
from collections import deque


class RuntimeEventBus:
    """In-memory event stream for live SSE log delivery."""

    def __init__(self, max_events=2000):
        self._lock = threading.Lock()
        self._events = deque(maxlen=max_events)
        self._next_id = 1

    def publish(self, event_type: str, message: str):
        with self._lock:
            event = {
                "id": self._next_id,
                "type": event_type,
                "message": message,
                "timestamp": time.time(),
            }
            self._events.append(event)
            self._next_id += 1
            return event["id"]

    def get_since(self, last_id: int):
        with self._lock:
            return [event for event in self._events if event["id"] > last_id]
