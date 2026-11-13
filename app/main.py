import asyncio
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, HttpUrl

from app import browser_client, policy, search
from app.cache import Cache
from app.config import Settings
from app.web import WebClient

logger = logging.getLogger("uvicorn.error")
bearer = HTTPBearer(auto_error=False)


class PageRequest(BaseModel):
    url: HttpUrl


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=5, ge=1, le=10)


class PageResponse(BaseModel):
    url: str
    text: str
    content_type: str = "text/plain"
    cache_hit: bool = False
    untrusted_content: bool = True


class SearchResponse(BaseModel):
    results: list[search.SearchResult]
    cache_hit: bool = False
    untrusted_content: bool = True


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings()
        app.state.settings = config
        app.state.web = WebClient(config)
        app.state.cache = Cache(config.cache_ttl_seconds, config.cache_entries)
        app.state.requests = defaultdict(deque)
        app.state.active = asyncio.Semaphore(config.max_concurrent_requests)
        app.state.browser_active = asyncio.Semaphore(1)
        yield

    app = FastAPI(title="Agent Gateway", version="0.2.0", lifespan=lifespan)

    async def authorize(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        config = request.app.state.settings
        if not credentials or not secrets.compare_digest(
            credentials.credentials.encode(), config.api_token.encode()
        ):
            raise HTTPException(401, "Invalid token", {"WWW-Authenticate": "Bearer"})
        limit = config.requests_per_minute
        if request.url.path == "/web-search":
            limit = config.search_requests_per_minute
        window = request.app.state.requests[request.url.path]
        now = time.monotonic()
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(429, "Gateway rate limit", {"Retry-After": "60"})
        window.append(now)

    @app.middleware("http")
    async def audit(request: Request, call_next):
        request_id = uuid4().hex
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                }
            )
        )
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.post("/fetch-page", dependencies=[Depends(authorize)], response_model=PageResponse)
    async def fetch_page(body: PageRequest, request: Request):
        url = str(body.url)
        await policy.inspect_input(url)
        cache = request.app.state.cache
        key = ("fetch", url)
        page = cache.get(key)
        cached = page is not None
        if page is None:
            async with request.app.state.active:
                page = await request.app.state.web.fetch(url)
            if page.cacheable:
                cache.put(key, page)
        await policy.inspect_output(page.text)
        return PageResponse(
            url=page.url, text=page.text, content_type=page.content_type, cache_hit=cached
        )

    @app.post("/browse-page", dependencies=[Depends(authorize)], response_model=PageResponse)
    async def browse_page(body: PageRequest, request: Request):
        url = str(body.url)
        await policy.inspect_input(url)
        await policy.validate_target(url, request.app.state.settings.allowed_domains)
        async with request.app.state.browser_active:
            result = await browser_client.browse(url, request.app.state.settings)
        await policy.inspect_output(result.text)
        return PageResponse(url=str(result.url), text=result.text)

    @app.post("/web-search", dependencies=[Depends(authorize)], response_model=SearchResponse)
    async def web_search(body: SearchRequest, request: Request):
        await policy.inspect_input(body.query)
        key = ("search", body.query, body.max_results)
        cache = request.app.state.cache
        results = cache.get(key)
        cached = results is not None
        if results is None:
            async with request.app.state.active:
                results = await search.search(
                    body.query,
                    body.max_results,
                    request.app.state.settings,
                    request.app.state.web,
                )
            cache.put(key, results)
        await policy.inspect_output(json.dumps([item.model_dump(mode="json") for item in results]))
        return SearchResponse(results=results, cache_hit=cached)

    return app


app = create_app()
