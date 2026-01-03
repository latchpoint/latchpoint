#!/bin/bash
set -e

USER_ID="${LOCAL_UID:-1000}"
GROUP_ID="${LOCAL_GID:-1000}"

groupadd -g "$GROUP_ID" -o appuser 2>/dev/null || true
useradd -u "$USER_ID" -g "$GROUP_ID" -o -m -d /home/appuser appuser 2>/dev/null || true

mkdir -p /home/appuser
chown -R appuser:appuser /home/appuser

cd /app

# If a command is provided, run it as the app user and skip the default startup.
if [ "$#" -gt 0 ]; then
  exec gosu appuser "$@"
fi

cd /app/backend

echo "Running migrations..."
gosu appuser python manage.py migrate --noinput

echo "Applying integration settings..."
gosu appuser python manage.py apply_integration_settings

echo "Starting Daphne..."
exec gosu appuser daphne -b 0.0.0.0 -p 8000 config.asgi:application

