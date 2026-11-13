FROM python:3.12-slim
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca \
        NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; \
    fi; \
    pip install --no-cache-dir uv==0.10.9 && uv sync --frozen --no-dev --extra browser --no-cache && \
    .venv/bin/playwright install --with-deps --only-shell chromium && \
    rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home gateway
COPY --chown=gateway:gateway app ./app
COPY --chown=gateway:gateway browser ./browser
USER gateway
EXPOSE 8000
CMD [".venv/bin/uvicorn", "browser.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
