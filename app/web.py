import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.policy import resolve_target


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


@dataclass
class Page:
    url: str
    content_type: str
    text: str
    cacheable: bool = True


@dataclass
class Resource:
    status: int
    headers: dict
    body: bytes


class WebClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def resource(self, url: str, headers: dict | None = None) -> Resource:
        host, address = await resolve_target(url, self.settings.allowed_domains)
        target = httpx.URL(url).copy_with(host=address, fragment=None)
        try:
            async with httpx.AsyncClient(
                trust_env=False, timeout=self.settings.timeout_seconds
            ) as client:
                async with client.stream(
                    "GET",
                    target,
                    headers={"User-Agent": "AgentGateway/0.2", **(headers or {}), "Host": host},
                    extensions={"sni_hostname": host},
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.settings.max_response_bytes:
                            raise HTTPException(413, "Upstream response is too large")
                        body.extend(chunk)
                    return Resource(response.status_code, dict(response.headers), bytes(body))
        except httpx.TimeoutException:
            raise HTTPException(504, "Upstream request timed out") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Upstream connection failed") from None

    async def fetch(self, url: str, headers: dict | None = None) -> Page:
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                return await self._fetch(url, headers)
        except TimeoutError:
            raise HTTPException(504, "Upstream request timed out") from None

    async def _fetch(self, url: str, headers: dict | None) -> Page:
        for redirect in range(6):
            response = await self.resource(url, headers)
            if response.status in (301, 302, 303, 307, 308):
                if headers or redirect == 5 or "location" not in response.headers:
                    raise HTTPException(502, "Upstream redirect rejected")
                url = urljoin(url, response.headers["location"])
                continue
            if response.status == 429:
                retry_after = response.headers.get("retry-after", "60")
                raise HTTPException(429, "Upstream rate limit", {"Retry-After": retry_after})
            if response.status >= 400:
                raise HTTPException(502, f"Upstream returned HTTP {response.status}")
            content_type = response.headers.get("content-type", "").split(";")[0]
            if content_type not in (
                "text/html",
                "text/plain",
                "application/json",
                "application/xhtml+xml",
            ):
                raise HTTPException(415, "Only HTML, plain text and JSON are supported")
            text = response.body.decode("utf-8", errors="replace")
            if content_type in ("text/html", "application/xhtml+xml"):
                parser = TextExtractor()
                parser.feed(text)
                text = "\n".join(parser.parts)
            cache_control = response.headers.get("cache-control", "").lower()
            cacheable = not any(
                value in cache_control for value in ("no-store", "no-cache", "private")
            )
            return Page(url, content_type, text, cacheable)
        raise HTTPException(502, "Too many redirects")
