import httpx
from fastapi import HTTPException
from pydantic import BaseModel, HttpUrl

from app.config import Settings


class BrowserResult(BaseModel):
    url: HttpUrl
    text: str


async def browse(url: str, settings: Settings) -> BrowserResult:
    if not settings.browser_url or len(settings.browser_token) < 32:
        raise HTTPException(503, "Browser worker is not configured")
    try:
        async with httpx.AsyncClient(
            trust_env=False, timeout=settings.browser_timeout_seconds
        ) as client:
            response = await client.post(
                f"{settings.browser_url}/render",
                headers={"Authorization": f"Bearer {settings.browser_token}"},
                json={"url": url},
            )
        if response.status_code != 200:
            status = response.status_code if response.status_code in (403, 413, 429, 504) else 502
            raise HTTPException(status, "Browser worker could not render the page")
        result = BrowserResult.model_validate(response.json())
        if len(result.text.encode()) > settings.max_response_bytes:
            raise HTTPException(413, "Rendered content is too large")
        return result
    except httpx.TimeoutException:
        raise HTTPException(504, "Browser startup or render timed out") from None
    except httpx.HTTPError:
        raise HTTPException(502, "Browser worker is unavailable") from None
    except ValueError:
        raise HTTPException(502, "Invalid browser worker response") from None
