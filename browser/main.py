import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, HttpUrl

from app.config import Settings
from app.policy import validate_target
from app.web import WebClient

bearer = HTTPBearer(auto_error=False)


class RenderRequest(BaseModel):
    url: HttpUrl


async def render(url: str, settings: Settings) -> dict:
    from playwright.async_api import Error, async_playwright
    from playwright.async_api import TimeoutError as BrowserTimeoutError

    await validate_target(url, settings.allowed_domains)
    web = WebClient(settings)
    request_count = 0
    total_bytes = 0
    blocked = None

    async def intercept(route):
        nonlocal request_count, total_bytes, blocked
        request_count += 1
        if route.request.method not in ("GET", "HEAD"):
            await route.abort()
            return
        if route.request.resource_type in ("image", "media", "font"):
            await route.abort()
            return
        try:
            if request_count > 50:
                raise HTTPException(413, "Page requested too many resources")
            async with asyncio.timeout(settings.timeout_seconds):
                resource = await web.resource(route.request.url)
            total_bytes += len(resource.body)
            if total_bytes > settings.max_response_bytes * 5:
                raise HTTPException(413, "Page resources are too large")
            headers = {
                key: value
                for key, value in resource.headers.items()
                if key
                not in ("content-encoding", "content-length", "transfer-encoding", "set-cookie")
            }
            await route.fulfill(status=resource.status, headers=headers, body=resource.body)
        except (HTTPException, TimeoutError) as error:
            blocked = error
            await route.abort()

    try:
        async with asyncio.timeout(45), async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                executable_path=settings.chromium_executable,
                args=[
                    "--disable-background-networking",
                    "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
            )
            try:
                context = await browser.new_context(service_workers="block", accept_downloads=False)
                await context.route("**/*", intercept)
                await context.route_web_socket("**/*", lambda socket: socket.close())
                page = await context.new_page()
                response = await page.goto(url, wait_until="networkidle", timeout=30_000)
                if blocked:
                    raise blocked
                if response is None or response.status >= 400:
                    status = 429 if response and response.status == 429 else 502
                    raise HTTPException(status, "Page returned an upstream error")
                await validate_target(page.url, settings.allowed_domains)
                text = await page.locator("body").inner_text(timeout=5000)
                if len(text.encode()) > settings.max_response_bytes:
                    raise HTTPException(413, "Rendered content is too large")
                return {"url": page.url, "text": text}
            finally:
                await browser.close()
    except (BrowserTimeoutError, TimeoutError):
        raise HTTPException(504, "Browser render timed out") from None
    except Error:
        if isinstance(blocked, HTTPException):
            raise blocked
        raise HTTPException(502, "Browser navigation failed") from None


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings()
        app.state.active = asyncio.Semaphore(1)
        yield

    app = FastAPI(title="Browser Worker", lifespan=lifespan, docs_url=None, redoc_url=None)

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        expected = app.state.settings.api_token
        if not credentials or not secrets.compare_digest(
            credentials.credentials.encode(), expected.encode()
        ):
            raise HTTPException(401, "Invalid worker token")

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.post("/render", dependencies=[Depends(authorize)])
    async def render_page(body: RenderRequest):
        if app.state.active.locked():
            raise HTTPException(429, "Browser worker is busy", {"Retry-After": "10"})
        async with app.state.active:
            return await render(str(body.url), app.state.settings)

    return app


app = create_app()
