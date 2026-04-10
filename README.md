<p align="center">
  <img src="frontend/public/latchpoint_brand.png" alt="LatchPoint" width="240" />
</p>

A home security alarm panel system built with Django and React. Integrates with Home Assistant, MQTT, Z-Wave JS, and Frigate.

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
| DEBUG | Enable debug mode | False |
| LOG_LEVEL | Logging level | INFO |
| ALLOWED_HOSTS | Comma-separated allowed hosts | localhost,127.0.0.1 |
| DATABASE_URL | PostgreSQL connection URL | SQLite fallback |
| CSRF_TRUSTED_ORIGINS | Trusted origins for CSRF | Auto-configured in debug |
| CORS_ALLOWED_ORIGINS | Allowed CORS origins | - |
| **Home Assistant** | | |
| HA_ENABLED | Enable Home Assistant integration | false |
| HA_BASE_URL | Home Assistant base URL | http://localhost:8123 |
| HA_TOKEN | Long-lived access token | - |
| **MQTT** | | |
| MQTT_ENABLED | Enable MQTT transport | false |
| MQTT_HOST | MQTT broker hostname | localhost |
| MQTT_PORT | MQTT broker port | 1883 |
| MQTT_USERNAME | MQTT username | - |
| MQTT_PASSWORD | MQTT password | - |
| MQTT_USE_TLS | Use TLS for MQTT | false |
| MQTT_TLS_INSECURE | Skip TLS certificate verification | false |
| MQTT_CLIENT_ID | MQTT client ID | latchpoint-alarm |
| **Z-Wave JS** | | |
| ZWAVEJS_ENABLED | Enable Z-Wave JS integration | false |
| ZWAVEJS_WS_URL | Z-Wave JS WebSocket URL | ws://localhost:3000 |
| ZWAVEJS_API_TOKEN | Z-Wave JS API token | - |
| **Zigbee2MQTT** | | |
| ZIGBEE2MQTT_ENABLED | Enable Zigbee2MQTT integration | false |
| **Frigate** | | |
| FRIGATE_ENABLED | Enable Frigate integration | false |
| **Notifications** | | |
| PUSHBULLET_ENABLED | Enable Pushbullet notifications | false |
| PUSHBULLET_ACCESS_TOKEN | Pushbullet access token | - |
| DISCORD_ENABLED | Enable Discord notifications | false |
| DISCORD_WEBHOOK_URL | Discord webhook URL | - |
| SLACK_ENABLED | Enable Slack notifications | false |
| SLACK_BOT_TOKEN | Slack bot token | - |
| WEBHOOK_ENABLED | Enable generic webhook | false |
| WEBHOOK_URL | Webhook URL | - |

Operational settings (timeouts, keepalive, reconnect intervals) are managed via the Settings UI and stored in the database.
