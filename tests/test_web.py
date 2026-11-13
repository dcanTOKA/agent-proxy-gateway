from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.config import Proxy, Settings
from app.web import WebClient


@pytest.fixture
def web(monkeypatch):
    settings = Settings(
        _env_file=None,
        api_token="a" * 40,
        proxies=[Proxy(name="one", url="http://10.40.2.10:3128")],
        allowed_domains=["example.com"],
        max_response_bytes=1024,
    )
    monkeypatch.setattr("app.web.validate_target", AsyncMock(return_value="example.com"))
    return WebClient(settings)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.web.httpx.AsyncClient", client)
    return options


async def test_fetch_always_uses_proxy_and_removes_scripts(web, monkeypatch):
    options = transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<h1>Hello</h1><script>bad()</script><p>World</p>",
        ),
    )
    page = await web.fetch("https://example.com", web.settings.proxies[0])
    assert page.text == "Hello\nWorld"
    assert options[0]["proxy"] == "http://10.40.2.10:3128"
    assert options[0]["trust_env"] is False


async def test_redirect_target_revalidated(web, monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            302, headers={"location": "http://169.254.169.254/metadata"}
        ),
    )
    check = AsyncMock(side_effect=["example.com", HTTPException(403, "blocked")])
    monkeypatch.setattr("app.web.validate_target", check)
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com", web.settings.proxies[0])
    assert error.value.status_code == 403
    assert check.call_args.args[0] == "http://169.254.169.254/metadata"


async def test_provider_credentials_never_follow_redirect(web, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/"})

    transport(monkeypatch, handler)
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com", web.settings.proxies[0], {"Secret": "key"})
    assert error.value.status_code == 502
    assert len(calls) == 1


async def test_429_preserves_retry_after_without_rotation(web, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "120"})

    transport(monkeypatch, handler)
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com", web.settings.proxies[0])
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "120"
    assert len(calls) == 1


async def test_response_size_limit(web, monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"x" * 2048
        ),
    )
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com", web.settings.proxies[0])
    assert error.value.status_code == 413


async def test_proxy_failure_has_no_direct_fallback(web, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("offline")

    transport(monkeypatch, handler)
    with pytest.raises(HTTPException) as error:
        await web.fetch("https://example.com", web.settings.proxies[0])
    assert error.value.status_code == 502
    assert len(calls) == 1
