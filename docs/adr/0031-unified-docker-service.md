# ADR-0031: Unified Docker Service for Frontend and Backend

## Status
Accepted

## Context
The project currently runs two separate Docker services:
- `web`: Django/Daphne backend on port 8000 (exposed as 5427)
- `frontend`: Node.js/Vite dev server on port 5428

This separation creates operational complexity:
1. Two containers to manage, monitor, and debug
2. Two exposed ports requiring CORS configuration
3. Separate build and deployment pipelines
4. Inconsistent developer experience between local and containerized development

### Current Architecture
```
┌─────────────────┐     ┌─────────────────┐
│  frontend:5428  │     │    web:5427     │
│  (Vite + React) │     │ (Daphne+Django) │
└─────────────────┘     └─────────────────┘
        │                       │
        ▼                       ▼
   Browser :5428          Browser :5427
   (UI assets)            (API + WebSocket)
```

### Requirements
1. **Development**: Hot module replacement (HMR) for frontend changes
2. **Production**: Optimized static file serving
3. **Single entry point**: One port for both UI and API
4. **WebSocket support**: Proper upgrade handling for `/ws/` paths
5. **Simplicity**: Minimal configuration changes between dev and prod

## Decision
Consolidate `web` and `frontend` into a single `app` service with mode-based behavior:
- **Development** (`docker-compose.yml`): Vite dev server with HMR + Daphne
- **Production** (`docker-compose.prod.yml`): Nginx serving built assets + Daphne

### Target Architecture

#### Development Mode
```
┌─────────────────────────────────────────┐
│              app container              │
│  ┌─────────────┐    ┌─────────────┐    │
│  │ Vite (3000) │───▶│ Daphne(8000)│    │
│  │ HMR enabled │/api│             │    │
│  │             │/ws │             │    │
│  └─────────────┘    └─────────────┘    │
│         │                              │
└─────────┼──────────────────────────────┘
          ▼
     Browser :5427
```

#### Production Mode
```
┌─────────────────────────────────────────┐
│              app container              │
│  ┌─────────────┐    ┌─────────────┐    │
│  │ Nginx (80)  │───▶│ Daphne(8000)│    │
│  │static files │/api│             │    │
│  │             │/ws │             │    │
│  └─────────────┘    └─────────────┘    │
│         │                              │
└─────────┼──────────────────────────────┘
          ▼
     Browser :5427
```

### Implementation

#### 1. Multi-Stage Dockerfile

```dockerfile
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
```

#### 2. Nginx Configuration (`docker/nginx.conf`)

```nginx
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent"';

    access_log /var/log/nginx/access.log main;
    sendfile on;
    keepalive_timeout 65;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    upstream daphne {
        server 127.0.0.1:8000;
    }

    server {
        listen 80;
        server_name _;
        root /app/frontend/dist;

        # API proxy
        location /api/ {
            proxy_pass http://daphne;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # WebSocket proxy
        location /ws/ {
            proxy_pass http://daphne;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 86400;
        }

        # Static files with cache headers
        location /assets/ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        # SPA fallback - serve index.html for client-side routing
        location / {
            try_files $uri $uri/ /index.html;
        }
    }
}
```

#### 3. Supervisord Configurations

**Development** (`docker/supervisord.dev.conf`):
```ini
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0

[program:daphne]
command=gosu appuser daphne -b 0.0.0.0 -p 8000 config.asgi:application
directory=/app/backend
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:vite]
command=gosu appuser npm run dev -- --host 0.0.0.0 --port 3000
directory=/app/frontend
environment=HOME="/home/appuser",NPM_CONFIG_CACHE="/home/appuser/.npm"
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
```

**Production** (`docker/supervisord.prod.conf`):
```ini
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:daphne]
command=gosu appuser daphne -b 127.0.0.1 -p 8000 config.asgi:application
directory=/app/backend
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
```

#### 4. Entrypoint Script (`docker/entrypoint.sh`)

```bash
#!/bin/bash
set -e

USER_ID="${LOCAL_UID:-1000}"
GROUP_ID="${LOCAL_GID:-1000}"

# Create group/user with matching host IDs at runtime
# This ensures files in volumes have correct ownership outside the container
groupadd -g "$GROUP_ID" -o appuser 2>/dev/null || true
useradd -u "$USER_ID" -g "$GROUP_ID" -o -m -d /home/appuser appuser 2>/dev/null || true

# Set user for supervisord child processes
export APP_USER=appuser

# Ensure writable directories exist with correct ownership
mkdir -p /home/appuser/.npm
chown -R appuser:appuser /home/appuser

cd /app/backend

# Run migrations as appuser
echo "Running migrations..."
gosu appuser python manage.py migrate --noinput

# Apply integration settings
echo "Applying integration settings..."
gosu appuser python manage.py apply_integration_settings

# Development-specific setup
if [ "$MODE" = "development" ]; then
    echo "Development mode: Installing frontend dependencies..."
    cd /app/frontend
    # Fix ownership of node_modules (anonymous volume is created as root)
    chown appuser:appuser /app/frontend/node_modules 2>/dev/null || mkdir -p /app/frontend/node_modules && chown appuser:appuser /app/frontend/node_modules
    gosu appuser npm install
    cd /app
fi

echo "Starting services in $MODE mode..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/app.conf
```

#### 5. Docker Compose Files

**Development** (`docker-compose.yml`):
```yaml
services:
  db:
    image: postgres:15
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-alarm_db}
      POSTGRES_USER: ${POSTGRES_USER:-alarm}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-alarm}
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    build:
      context: .
      target: development
    environment:
      LOCAL_UID: ${LOCAL_UID:-1000}
      LOCAL_GID: ${LOCAL_GID:-1000}
      HOME: /tmp
      NPM_CONFIG_CACHE: /tmp/.npm
    env_file:
      - .env
    ports:
      - "5427:3000"
    depends_on:
      - db
    volumes:
      - .:/app
      - /app/frontend/node_modules  # Anonymous volume for node_modules

volumes:
  db_data:
```

**Production** (`docker-compose.prod.yml`):
```yaml
services:
  db:
    image: postgres:15
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-alarm_db}
      POSTGRES_USER: ${POSTGRES_USER:-alarm}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-alarm}
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    build:
      context: .
      target: production
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "5427:80"
    depends_on:
      - db

volumes:
  db_data:
```

#### 6. Vite Configuration Update

Update `frontend/vite.config.ts` to use port 3000 internally:

```typescript
server: {
  port: 3000,  // Changed from 5173
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
    '/ws': {
      target: 'ws://127.0.0.1:8000',
      ws: true,
    },
  },
},
```

### Directory Structure

```
alarm/
├── docker/
│   ├── nginx.conf
│   ├── supervisord.dev.conf
│   ├── supervisord.prod.conf
│   └── entrypoint.sh
├── docker-compose.yml          # Development (default)
├── docker-compose.prod.yml     # Production
├── Dockerfile                  # Multi-stage build
├── backend/
│   └── ...
└── frontend/
    └── ...
```

### Usage

| Command | Mode | Description |
|---------|------|-------------|
| `docker compose up` | Dev | HMR enabled, source mounted |
| `docker compose up --build` | Dev | Rebuild with latest changes |
| `docker compose -f docker-compose.prod.yml up --build` | Prod | Built assets, optimized |

## Alternatives Considered

### 1. Keep Separate Services
- **Pros**: Simpler Dockerfiles, independent scaling
- **Cons**: Two ports, CORS complexity, harder to reason about
- **Verdict**: Rejected - operational overhead outweighs benefits for this project

### 2. Nginx in Separate Container
- **Pros**: Cleaner separation, standard pattern
- **Cons**: Three containers, more complexity
- **Verdict**: Rejected - overkill for single-instance deployment

### 3. Django Serving Static Files (WhiteNoise)
- **Pros**: Single process, no Nginx
- **Cons**: Less efficient for static files, no WebSocket buffering
- **Verdict**: Rejected - Nginx provides better static file performance

### 4. Traefik/Caddy as Reverse Proxy
- **Pros**: Modern, auto-TLS, dynamic configuration
- **Cons**: Another service to configure and maintain
- **Verdict**: Future consideration for multi-service deployment

## Consequences

### Positive
- Single port (5427) for all traffic
- Consistent experience between dev and prod
- Simplified debugging (one container to inspect)
- No CORS configuration needed
- HMR works in development
- Optimized production builds with proper caching

### Negative
- Larger development image (includes Node.js)
- Supervisord adds complexity vs single-process containers
- Longer initial build time for production image

### Mitigations
- Use Docker layer caching effectively
- Development image can be pre-pulled
- Consider BuildKit for faster builds

## Migration Path

1. Create `docker/` directory with new configuration files
2. Update `Dockerfile` with multi-stage build
3. Create `docker-compose.prod.yml`
4. Update `docker-compose.yml` with new service definition
5. Update `frontend/vite.config.ts` port configuration
6. Test development workflow (HMR, API proxy, WebSocket)
7. Test production build and deployment
8. Remove old `backend/Dockerfile` (if separate)
9. Update deployment documentation

## Todos

### Phase 1 (MVP)
- [ ] Create `docker/` directory
- [ ] Create `docker/nginx.conf`
- [ ] Create `docker/supervisord.dev.conf`
- [ ] Create `docker/supervisord.prod.conf`
- [ ] Create `docker/entrypoint.sh`
- [ ] Update `Dockerfile` with multi-stage build
- [ ] Update `docker-compose.yml` for development
- [ ] Create `docker-compose.prod.yml` for production
- [ ] Update `frontend/vite.config.ts` proxy configuration
- [ ] Test development mode (HMR, API, WebSocket)
- [ ] Test production mode (static files, API, WebSocket)
- [ ] Update AGENTS.md with new Docker workflow

### Phase 2 (Future)
- [ ] Add health check endpoints for container orchestration
- [ ] Consider Docker BuildKit optimizations
- [ ] Add container resource limits
- [ ] Consider multi-architecture builds (arm64)
