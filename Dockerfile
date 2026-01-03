# =============================================================================
# Stage 1: Frontend build (production only)
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
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
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        supervisor \
        nginx \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 3: Development image
# =============================================================================
FROM base AS development

# Install Node.js for Vite dev server
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
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
COPY requirements.txt /app/

# Copy configuration files
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/supervisord.prod.conf /etc/supervisor/conf.d/app.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV MODE=production
EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
