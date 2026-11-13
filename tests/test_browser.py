from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.cache import Cache
from app.config import Settings
from browser.main import create_app


def test_worker_requires_its_own_token(monkeypatch):
    settings = Settings(_env_file=None, api_token="w" * 40, allowed_domains=["example.com"])
    render = AsyncMock(return_value={"url": "https://example.com", "text": "hello"})
    monkeypatch.setattr("browser.main.render", render)
    with TestClient(create_app(settings)) as client:
        response = client.post("/render", json={"url": "https://example.com"})
        assert response.status_code == 401
        render.assert_not_called()
        response = client.post(
            "/render",
            headers={"Authorization": "Bearer " + "w" * 40},
            json={"url": "https://example.com"},
        )
        assert response.status_code == 200


def test_cache_expiration_and_capacity(monkeypatch):
    now = [0]
    monkeypatch.setattr("app.cache.time.monotonic", lambda: now[0])
    cache = Cache(ttl=10, capacity=1)
    cache.put("a", "first")
    cache.put("b", "second")
    assert cache.get("a") is None
    assert cache.get("b") == "second"
    now[0] = 11
    assert cache.get("b") is None


@pytest.mark.asyncio
async def test_browser_client_requires_configuration():
    from app.browser_client import browse

    settings = Settings(_env_file=None, api_token="a" * 40, allowed_domains=["example.com"])
    with pytest.raises(HTTPException) as error:
        await browse("https://example.com", settings)
    assert error.value.status_code == 503
