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

cd /app

# If a command is provided (e.g. `docker compose run app sh` or `... python manage.py test`),
# run it as the app user and skip starting supervisord.
if [ "$#" -gt 0 ]; then
    exec gosu appuser "$@"
fi

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
