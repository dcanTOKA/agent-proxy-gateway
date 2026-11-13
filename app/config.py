from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    api_token: str = Field(min_length=32)
    allowed_domains: list[str] = Field(min_length=1)
    search_provider: Literal["none", "brave"] = "none"
    search_api_key: str = ""
    browser_url: str = ""
    browser_token: str = ""
    chromium_executable: str | None = None
    browser_timeout_seconds: float = Field(default=150, gt=0, le=180)
    requests_per_minute: int = Field(default=60, ge=1)
    search_requests_per_minute: int = Field(default=10, ge=1)
    timeout_seconds: float = Field(default=30, gt=0, le=60)
    max_response_bytes: int = Field(default=2_000_000, ge=1024, le=5_000_000)
    max_concurrent_requests: int = Field(default=10, ge=1, le=100)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=3600)
    cache_entries: int = Field(default=32, ge=1, le=128)

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        normalized = [domain.lower().strip().rstrip(".") for domain in domains]
        if any(not domain or any(c in domain for c in "/:*@ ") for domain in normalized):
            raise ValueError("Use explicit domain names without wildcards, schemes or ports")
        return normalized

    @field_validator("browser_url")
    @classmethod
    def validate_browser_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if value and (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Browser URL must be an HTTP(S) origin without credentials")
        return value.rstrip("/")
