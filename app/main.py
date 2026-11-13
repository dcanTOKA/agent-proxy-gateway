import asyncio
import json
import logging
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, HttpUrl

from app import policy
from app.config import Settings
from app.proxies import ProxyPool
from app.web import WebClient

logger = logging.getLogger("uvicorn.error")
bearer = HTTPBearer(auto_error=False)


class FetchRequest(BaseModel):
    url: HttpUrl
    session_id: str | None = Field(default=None, max_length=128)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=5, ge=1, le=10)
    session_id: str | None = Field(default=None, max_length=128)


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str


class FetchResponse(BaseModel):
    url: str
    content_type: str
    text: str
    proxy: str
    untrusted_content: bool = True


class SearchResponse(BaseModel):
    results: list[SearchResult]
    proxy: str
    untrusted_content: bool = True


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings()
        app.state.settings = config
        app.state.pool = ProxyPool(config.proxies)
        app.state.web = WebClient(config)
        app.state.requests = deque()
        app.state.active = asyncio.Semaphore(config.max_concurrent_requests)
        yield

    app = FastAPI(title="Agent Gateway", version="0.1.0", lifespan=lifespan)

    async def authorize(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        token = request.app.state.settings.api_token
        if not credentials or not secrets.compare_digest(
            credentials.credentials.encode(), token.encode()
        ):
            raise HTTPException(401, "Invalid token", {"WWW-Authenticate": "Bearer"})
        now = time.monotonic()
        window = request.app.state.requests
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= request.app.state.settings.requests_per_minute:
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

    @app.post("/fetch-page", dependencies=[Depends(authorize)], response_model=FetchResponse)
    async def fetch_page(body: FetchRequest, request: Request):
        await policy.inspect_input(str(body.url))
        proxy = request.app.state.pool.choose(body.session_id)
        async with request.app.state.active:
            page = await request.app.state.web.fetch(str(body.url), proxy)
        await policy.inspect_output(page.text)
        return FetchResponse(
            url=page.url, content_type=page.content_type, text=page.text, proxy=proxy.name
        )

    @app.post("/web-search", dependencies=[Depends(authorize)], response_model=SearchResponse)
    async def web_search(body: SearchRequest, request: Request):
        settings = request.app.state.settings
        if not settings.search_api_key:
            raise HTTPException(503, "Search provider is not configured")
        await policy.inspect_input(body.query)
        from urllib.parse import urlencode

        query = urlencode({"q": body.query, "count": body.max_results})
        url = f"https://api.search.brave.com/res/v1/web/search?{query}"
        proxy = request.app.state.pool.choose(body.session_id)
        async with request.app.state.active:
            page = await request.app.state.web.fetch(
                url, proxy, {"X-Subscription-Token": settings.search_api_key}
            )
        try:
            payload = json.loads(page.text)
            results = [
                SearchResult(
                    title=item.get("title", ""),
                    url=item["url"],
                    snippet=item.get("description", ""),
                )
                for item in payload.get("web", {}).get("results", [])[: body.max_results]
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(502, "Invalid search provider response") from None
        await policy.inspect_output(json.dumps([item.model_dump(mode="json") for item in results]))
        return SearchResponse(results=results, proxy=proxy.name)

    return app


app = create_app()
