import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException

from app.config import Proxy, Settings
from app.policy import validate_target


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


class WebClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def fetch(self, url: str, proxy: Proxy, headers: dict | None = None) -> Page:
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                return await self._fetch(url, proxy, headers)
        except (TimeoutError, httpx.TimeoutException):
            raise HTTPException(504, "Upstream request timed out") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Proxy or upstream connection failed") from None

    async def _fetch(self, url: str, proxy: Proxy, headers: dict | None) -> Page:
        async with httpx.AsyncClient(
            proxy=proxy.url,
            trust_env=False,
            follow_redirects=False,
            timeout=self.settings.timeout_seconds,
            headers={"User-Agent": "AgentGateway/0.1", **(headers or {})},
        ) as client:
            for redirect in range(6):
                await validate_target(url, self.settings.allowed_domains)
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        # Provider credentials must never follow redirects.
                        if headers or redirect == 5 or "location" not in response.headers:
                            raise HTTPException(502, "Upstream redirect rejected")
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code == 429:
                        retry_after = response.headers.get("retry-after", "60")
                        raise HTTPException(
                            429, "Upstream rate limit", {"Retry-After": retry_after}
                        )
                    if response.is_error:
                        raise HTTPException(502, f"Upstream returned HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";")[0]
                    if content_type not in (
                        "text/html",
                        "text/plain",
                        "application/json",
                        "application/xhtml+xml",
                    ):
                        raise HTTPException(415, "Only HTML, plain text and JSON are supported")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self.settings.max_response_bytes:
                            raise HTTPException(413, "Upstream response is too large")
                    text = chunks.decode("utf-8", errors="replace")
                    if content_type in ("text/html", "application/xhtml+xml"):
                        parser = TextExtractor()
                        parser.feed(text)
                        text = "\n".join(parser.parts)
                    return Page(str(response.url), content_type, text)
        raise HTTPException(502, "Too many redirects")
