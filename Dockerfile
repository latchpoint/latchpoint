# =============================================================================
# Stage 1: Frontend build (production only)
# =============================================================================
FROM node:24-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund

# Build args auto-injected by misc-actions docker-build-push
ARG GIT_COMMIT_SHORT=""
ARG BUILD_REPO=""

# Copy pyproject.toml for version extraction during frontend build
COPY pyproject.toml /app/pyproject.toml

COPY frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Runtime base
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies including gosu for privilege dropping
# tzdata: ships the IANA database so the container honors `TZ` without
# depending on host /etc/localtime / /etc/timezone bind-mounts (ADR-0090).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        supervisor \
        nginx \
        curl \
        gosu \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from the uv lockfile.
# uv.lock is the single source of truth -- CI already resolves with `uv sync --frozen`,
# so exporting the same lock here keeps image builds byte-identical to CI. The export is
# fully hash-pinned, which also gates the supply chain (the old floating `>=` ranges in
# requirements.txt had no integrity check). Installing with --system keeps packages in the
# system interpreter, so bare `python`/`daphne` in the entrypoint and supervisord configs
# resolve exactly as before -- and nothing can be shadowed by the dev `.:/app` bind mount.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv
COPY pyproject.toml uv.lock /app/
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.lock && \
    uv pip install --system --no-cache -r /tmp/requirements.lock && \
    rm /tmp/requirements.lock

# =============================================================================
# Stage 3: Development image
# =============================================================================
FROM base AS development

# Install Node.js for Vite dev server
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Copy configuration files
COPY docker/supervisord.dev.conf /etc/supervisor/conf.d/app.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV MODE=development
EXPOSE 3000

ENTRYPOINT ["/entrypoint.sh"]

# =============================================================================
# Stage 3b: Backend-only development image (split dev compose)
# =============================================================================
FROM base AS backend-development

# Copy configuration files
COPY docker/entrypoint.backend.dev.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV MODE=backend-development
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# =============================================================================
# Stage 4: Production image
# =============================================================================
FROM base AS production

# Copy built frontend from builder stage
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy backend code
COPY backend /app/backend

# Copy configuration files
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/supervisord.prod.conf /etc/supervisor/conf.d/app.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV MODE=production
EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
