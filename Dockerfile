FROM python:3.11-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir uv

FROM base AS deps
COPY pyproject.toml .
RUN uv pip install --system --no-cache .
# Download chromium browser + install its system deps
RUN playwright install chromium --with-deps

FROM base AS production
# Python packages
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
# Playwright browser binary (already downloaded in deps stage)
COPY --from=deps /root/.cache/ms-playwright /root/.cache/ms-playwright
# Install only system runtime libs playwright needs (no browser download)
RUN playwright install-deps chromium
COPY . .
CMD ["python", "-m", "src.main"]
