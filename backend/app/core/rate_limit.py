from collections import defaultdict
from datetime import datetime, timezone
class InMemoryRateLimiter:
    def __init__(self, max_attempts: int = 10, window_seconds: int = 60): self.max_attempts=max_attempts; self.window_seconds=window_seconds; self._events=defaultdict(list)
    def allow(self, key: str) -> bool:
        now=datetime.now(timezone.utc).timestamp(); events=[x for x in self._events[key] if now-x<self.window_seconds]; self._events[key]=events
        if len(events)>=self.max_attempts: return False
        events.append(now); return True
limiter=InMemoryRateLimiter()
