"""A small cache that forgets: entries expire after a time, and the least recently used one goes first when it is full."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable, Hashable, TypeVar

V = TypeVar("V")


class TTLCache:
    def __init__(self, maxsize: int = 128, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic):
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.maxsize, self.ttl, self._clock = maxsize, ttl, clock
        self._items: OrderedDict[Hashable, tuple[float, object]] = OrderedDict()
        self.hits = self.misses = 0

    def get_or_load(self, key: Hashable, load: Callable[[], V]) -> V:
        """The cached value for key, or load() if there is none or it has expired."""
        now = self._clock()
        entry = self._items.get(key)
        if entry is not None and entry[0] > now:
            self._items.move_to_end(key)          # most recently used goes to the back
            self.hits += 1
            return entry[1]
        self.misses += 1
        value = load()                            # may be slow: a query, a request
        self._items[key] = (now + self.ttl, value)
        self._items.move_to_end(key)
        self._evict(now)
        return value

    def _evict(self, now: float) -> None:
        """Drop what has expired, then the least recently used entries until the cache fits."""
        for key in [k for k, (expires, _) in self._items.items() if expires <= now]:
            del self._items[key]
        while len(self._items) > self.maxsize:
            self._items.popitem(last=False)       # the front is the least recently used

    def invalidate(self, key: Hashable) -> bool:
        return self._items.pop(key, None) is not None

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
