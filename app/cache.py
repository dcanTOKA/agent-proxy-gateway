import time
from collections import OrderedDict


class Cache:
    def __init__(self, ttl: int, capacity: int):
        self.ttl = ttl
        self.capacity = capacity
        self.entries = OrderedDict()

    def get(self, key):
        entry = self.entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() >= expires:
            del self.entries[key]
            return None
        self.entries.move_to_end(key)
        return value

    def put(self, key, value):
        if self.ttl == 0:
            return
        self.entries[key] = (time.monotonic() + self.ttl, value)
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
