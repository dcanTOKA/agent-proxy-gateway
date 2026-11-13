from hashlib import sha256
from itertools import cycle

from app.config import Proxy


class ProxyPool:
    def __init__(self, proxies: list[Proxy]):
        self.proxies = proxies
        self.rotation = cycle(proxies)

    def choose(self, session_id: str | None = None) -> Proxy:
        if session_id:
            return max(
                self.proxies,
                key=lambda proxy: sha256(f"{session_id}:{proxy.name}".encode()).digest(),
            )
        return next(self.rotation)
