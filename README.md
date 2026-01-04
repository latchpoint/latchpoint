<p align="center">
  <img src="frontend/public/latchpoint_brand.png" alt="LatchPoint" width="240" />
</p>

A home security alarm panel system built with Django and React. Integrates with Home Assistant, MQTT, Z-Wave JS, Frigate, and Zigbee2MQTT.

## Features

### Alarm System
- Multi-state alarm system (Disarmed, Armed Home, Armed Away, Armed Night, Armed Vacation, Pending, Triggered)
- Configurable arming and disarming delays
- Multiple settings profiles with switchable configurations
- Real-time WebSocket updates for instant state changes

### Authentication and Access Control
- PIN code system with multiple code types (permanent, temporary, one-time, service)
- Time-based and day-of-week restrictions for codes
- Two-factor authentication (TOTP)
- Role-based access control

### Rules Engine
- Automated trigger, disarm, arm, suppress, and escalate rules
- Priority-based execution with cooldown periods
- Rule simulation and testing before activation
- Comprehensive action logging

### Sensors
- Sensor registry linked to Home Assistant entities
- Entry point designation (doors/windows vs motion)
- Event logging for sensor triggers

### Integrations
- Home Assistant: Entity discovery, notification services, MQTT alarm entity publishing
- MQTT: Broker connection with TLS support
- Z-Wave JS: Device control, entity sync, Ring Keypad v2 support
- Frigate: Video surveillance with person/vehicle detection rules
- Zigbee2MQTT: Device sync and control

### Door Locks
- Door code management separate from alarm codes
- Code assignment to specific locks
- Usage audit logging

### Control Panels
- Physical keypad support (Ring Keypad v2 via Z-Wave)
- Per-device action mapping and volume control

### Event Logging
- Comprehensive audit trail for arm/disarm events, sensor triggers, and state transitions
- Failed code attempt tracking

## Production Setup

1. Create environment file:
```bash
cp .env.example .env
```

2. Configure required variables in `.env`:
```
SECRET_KEY=your-secure-secret-key
SETTINGS_ENCRYPTION_KEY=your-encryption-key
DEBUG=False
ALLOWED_HOSTS=your-domain.com
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

3. Pull and run the production container (published to GHCR):
```bash
docker pull ghcr.io/latchpoint/latchpoint:latest
docker run -d -p 80:80 --env-file .env ghcr.io/latchpoint/latchpoint:latest
```
Published tags include `latest` (default branch), `sha-...` (commit), and git tags.

Or with docker-compose for production:
```yaml
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: alarm_db
      POSTGRES_USER: alarm
      POSTGRES_PASSWORD: your-secure-password
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    image: ghcr.io/latchpoint/latchpoint:latest
    env_file:
      - .env
    ports:
      - "80:80"
    depends_on:
      - db

volumes:
  db_data:
```

4. Run migrations:
```bash
docker exec <container> python backend/manage.py migrate
```

5. Create a superuser:
```bash
docker exec -it <container> python backend/manage.py createsuperuser
```

## Development Setup

1. Create environment file:
```bash
cp .env.example .env
```

2. Start the development environment:
```bash
docker compose up --build
```

3. Access the application at `http://localhost:5427`

The development setup:
- Runs Vite dev server with hot module replacement
- Proxies API and WebSocket requests to Django backend
- Mounts source code for live reloading
- Uses PostgreSQL database (or SQLite if DATABASE_URL is omitted)

### Running Commands

```bash
# Run migrations
docker compose exec app python backend/manage.py migrate

# Create superuser
docker compose exec -it app python backend/manage.py createsuperuser

# Run tests
docker compose exec app python backend/manage.py test

# Access Django shell
docker compose exec app python backend/manage.py shell
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| SECRET_KEY | Django secret key | Required |
| SETTINGS_ENCRYPTION_KEY | Key for encrypting integration credentials | Required |
| DEBUG | Enable debug mode | False |
| LOG_LEVEL | Logging level | INFO |
| ALLOWED_HOSTS | Comma-separated allowed hosts | localhost,127.0.0.1 |
| DATABASE_URL | PostgreSQL connection URL | SQLite fallback |
| CSRF_TRUSTED_ORIGINS | Trusted origins for CSRF | Auto-configured in debug |
| CORS_ALLOWED_ORIGINS | Allowed CORS origins | - |
