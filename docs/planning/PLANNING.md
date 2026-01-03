# Home Assistant Alarm System - Planning Document

## Project Overview

A Django-based full-stack alarm system that integrates with Home Assistant, providing advanced access control, user management, and home security automation.

## Core Concept

Centralized alarm management system that leverages Home Assistant's device ecosystem while providing sophisticated access control, temporary codes, and security automation.

---

## Technology Stack

### Backend
- **Framework**: Django 5.x
- **API**: Django REST Framework
- **Real-time**: Django Channels (WebSocket support)
- **Task Queue**: Celery + Redis
- **Database**: PostgreSQL
- **Cache**: Redis

### Frontend
- **Framework**: React 18+ with TypeScript
- **Build Tool**: Vite
- **State Management**: Zustand (lightweight) + React Query (server state)
- **Routing**: React Router v6
- **Styling**: Tailwind CSS
- **Icons**: Heroicons or Lucide
- **Real-time**: Native WebSocket with reconnection logic
- **Forms**: React Hook Form + Zod validation
- **Testing**: Vitest + React Testing Library

#### Frontend Architecture
```
src/
├── components/
│   ├── alarm/           # Alarm control, keypad, status
│   ├── zones/           # Zone management UI
│   ├── codes/           # Code management
│   ├── automations/     # Automation builder
│   ├── settings/        # System settings
│   ├── common/          # Shared components
│   └── layout/          # App shell, nav, sidebar
├── hooks/               # Custom hooks (useAlarmState, useWebSocket)
├── stores/              # Zustand stores
├── services/            # API client, WebSocket manager
├── types/               # TypeScript interfaces
├── utils/               # Helpers, formatters
└── pages/               # Route components
```

#### Key Components
- **AlarmPanel**: Main dashboard with arm/disarm controls
- **Keypad**: Virtual keypad with PIN entry
- **ZoneMap**: Visual representation of zones/sensors
- **EventTimeline**: Real-time event feed
- **AutomationBuilder**: Visual automation editor
- **SettingsPanel**: Configuration management

### Integrations
- Home Assistant REST API & WebSocket API
- MQTT client (paho-mqtt)
- Frigate API for person detection

---

## Key Features

### 1. User Management & Authentication

#### User Onboarding
- First-run setup wizard if no users exist
- Admin account creation
- Home Assistant connection configuration
- Basic security settings

#### User Roles
- **Admin**: Full system control
- **Resident**: Can arm/disarm, manage own codes
- **Guest**: Limited access via temporary codes
- **Service**: For dog walkers, cleaners, etc. with scheduled access

#### Authentication
- Django authentication for web interface
- Optional 2FA (TOTP)
- Alarm code verification (4-8 digit PINs)
- Duress codes (silent alarm trigger)

### 2. Alarm Code Management

#### Permanent Codes
- User-specific PINs
- Admin codes (full access)
- Master code for emergency override
- Code usage tracking and logging

#### Temporary Codes
- Time-bound codes with:
  - Start date/time
  - End date/time
  - Days of week restrictions
  - Time window restrictions (e.g., 9am-5pm only)
- One-time use codes
- Usage count limits
- Auto-expiration and cleanup
- Guest profile association

#### Code Features
- Usage history and audit log
- Last used timestamp
- Entry point tracking
- Failed attempt monitoring
- Automatic lockout after X failed attempts
- Notifications on code usage (Email/SMS/Home Assistant/Push)

### 3. Alarm States & Modes

#### Alarm States
- **Disarmed**: All sensors inactive
- **Home/Stay**: Perimeter protection (doors/windows), interior motion disabled
- **Away**: Full protection, all sensors active
- **Night**: Similar to home but with some interior sensors
- **Vacation**: Away mode with additional automation (lights, etc.)

#### Entry/Exit Delays
- Configurable delay timers
- Different delays per entry point
- Countdown display/beeping
- Quick arm/disarm during delay

#### State Management
- State change logging
- Required authentication per state
- Scheduled state changes (e.g., auto-arm at bedtime)
- Geofencing integration for auto disarm when approaching

### 4. System Settings & Configuration

Inspired by Home Assistant's manual alarm integration, the system provides extensive configuration options for timing, behavior, and code requirements.

#### Global Timing Settings

**Delay Time** (Default: 60 seconds)
- Entry delay before alarm triggers
- Countdown period after entering while armed
- Allows time to disarm before triggering
- Configurable per-state override

**Arming Time** (Default: 60 seconds)
- Exit delay when arming the system
- Time to leave before alarm activates
- Countdown display during arming
- Configurable per-state override

**Trigger Time** (Default: 120 seconds)
- Duration alarm remains in triggered state
- How long sirens/alerts stay active
- After trigger time, system behavior depends on disarm_after_trigger setting
- Configurable per-state override

#### Behavioral Settings

**Disarm After Trigger** (Default: false)
- If true: System auto-disarms after trigger time expires
- If false: System returns to previously armed state after trigger time
- Security consideration: Auto-disarm may not be suitable for all installations

**Code Arm Required** (Default: true)
- Whether code is required to arm the system
- If false: Allows one-touch arming without authentication
- Disarm always requires code for security

**Available Arming States** (Optional restriction)
- Limit which arm modes are available to users
- Options: armed_away, armed_home, armed_night, armed_vacation, armed_custom_bypass
- If not specified, all states are available
- Useful for simplifying UI or restricting certain modes

#### Per-State Timing Overrides

Each alarm state can have custom timing that overrides global defaults:

**Disarmed State**
- Not typically used for timing overrides
- Can have custom entry behavior

**Armed Away**
- Example: Longer entry delay (90s) for fumbling with keys
- Example: Standard trigger time (120s)
- Full perimeter and interior protection

**Armed Home/Stay**
- Example: Shorter entry delay (30s) since you're home
- Example: Shorter trigger time (90s) for faster response
- Only perimeter protection active

**Armed Night**
- Example: Minimal entry delay (15s) - unexpected at night
- Example: Immediate or very short arming time (10s)
- Enhanced security during sleep hours

**Armed Vacation**
- Example: No entry delay (0s) - no one should be entering
- Example: Extended trigger time (300s) for monitoring service response
- Maximum security, no legitimate entry expected

**Armed Custom Bypass**
- User-defined timing based on specific scenario
- Example: Maintenance mode with extended delays

**Triggered State**
- Trigger time override
- Can have different siren patterns/durations

#### Code Configuration

**Code Requirement Matrix**
- Arm from disarmed: Optional (based on code_arm_required)
- Disarm from any armed state: Required (always)
- Change between armed states: Configurable
- Trigger manual panic: May bypass for emergency

**Code Templates**
- Dynamic code validation based on state transitions
- Different codes can be required for different state changes
- Variables available: from_state, to_state, user, time
- Example: Require master code to disarm from triggered state

#### Quick Actions

**Quick Arm**
- One-touch arming to specific state
- No code required (if code_arm_required is false)
- Common for "leaving home" scenario
- Example: Single button to arm_away

**Delayed Disarm**
- Enter code during entry delay
- Countdown visible to user
- Beep pattern indicates remaining time
- Cancel alarm before trigger

#### Audio/Visual Feedback Settings

**Beep Patterns**
- Entry delay: Slow beeps increasing to fast
- Exit delay: Steady beeps
- Armed: Single confirmation beep
- Disarmed: Two-tone confirmation
- Triggered: Continuous alarm tone

**Countdown Display**
- Show remaining seconds during delays
- Visual progress bar
- Color coding (green → yellow → red)
- Can be disabled for stealth mode

#### Sensor Behavior Settings

**Open Door/Window Warning**
- Warn if trying to arm with sensors open
- Option to bypass automatically
- List which sensors are preventing arming
- Force arm option (admin only)

**Sensor Delay Groups**
- Different entry delays for different entry points
- Example: Front door 60s, back door 30s, garage 45s
- Based on expected usage patterns

#### State Machine with Timing

The alarm system uses a state machine that incorporates timing for smooth transitions:

**Arming Flow:**
```
Disarmed → [Code entered to arm] → Arming (exit delay) → Armed
         └─ During arming period: countdown displayed
         └─ Can cancel during exit delay
         └─ After arming_time expires: transition to Armed state
```

**Entry Flow (Normal disarm):**
```
Armed → [Sensor triggered] → Pending (entry delay) → [Code entered] → Disarmed
      └─ During pending: countdown displayed
      └─ Beeps indicate urgency
      └─ Must enter code before delay_time expires
```

**Entry Flow (Failed disarm):**
```
Armed → [Sensor triggered] → Pending (entry delay) → [No code or wrong code] → Triggered
      └─ After delay_time expires without valid code
      └─ Triggers sirens/alerts
      └─ Remains triggered for trigger_time duration
```

**Triggered Flow (with disarm_after_trigger = false):**
```
Triggered → [trigger_time expires] → Returns to previous armed state
          └─ Or [Code entered during trigger] → Disarmed
```

**Triggered Flow (with disarm_after_trigger = true):**
```
Triggered → [trigger_time expires] → Disarmed
          └─ Or [Code entered during trigger] → Disarmed
```

**State Transitions Summary:**
- `disarmed` → `arming` (on arm command)
- `arming` → `armed_*` (after arming_time)
- `arming` → `disarmed` (on cancel/disarm during exit delay)
- `armed_*` → `pending` (on sensor trigger)
- `pending` → `disarmed` (on valid code)
- `pending` → `triggered` (after delay_time without code)
- `triggered` → `disarmed` (on valid code OR after trigger_time if disarm_after_trigger=true)
- `triggered` → `armed_*` (after trigger_time if disarm_after_trigger=false)

### 5. Home Assistant Integration

#### Configuration
- HA URL and Long-Lived Access Token (from environment)
- Entity discovery and mapping
- Connection health monitoring
- Automatic reconnection

#### Device Integration
- **Door/Window Sensors**: Monitor open/close state
- **Motion Sensors**: Detect movement
- **Locks**: Smart lock control (lock/unlock)
- **Cameras**: Frigate integration for person detection
- **Sirens/Alarms**: Trigger on alarm events
- **Lights**: Flash or turn on during alarms
- **Climate**: Integration for presence detection

#### Entity Management
- Map HA entities to alarm zones
- Configure which entities are active per alarm state
- Bypass individual sensors temporarily
- Entity state caching for offline resilience

#### Notification Service Discovery
- Auto-discover all available HA notify services
- Detect mobile app registrations
- Support for:
  - `notify.notify` (default service)
  - `notify.mobile_app_*` (iOS/Android apps)
  - `notify.telegram_*`
  - `notify.discord_*`
  - All other configured notify platforms
- Test notification capability before enabling
- Monitor service availability
- Graceful fallback if service unavailable

### 6. Zone Management

#### Zone Configuration
- Define areas: Entry, Perimeter, Interior, Garage, Basement, etc.
- Assign sensors to zones
- Per-zone settings:
  - Entry delay
  - Alarm response
  - Active in which modes
  - Notification preferences

#### Zone Features
- Zone bypass (temporary disable)
- Zone arm/disarm independently
- Chime on open (when disarmed)
- Zone status display

### 7. Event & Alert System

#### Event Types
- Alarm triggered
- Armed/disarmed
- Code used (with which code)
- Door/window opened
- Motion detected
- Person detected (Frigate)
- Sensor battery low
- System armed failed (sensor open)
- Network/HA connection issues

#### Notification Channels
- Web dashboard (real-time via WebSocket)
- **Home Assistant Notifications:**
  - Persistent notifications in HA UI
  - Mobile app push notifications
  - TTS (text-to-speech) announcements
  - Actionable notifications (dismiss, view camera, etc.)
  - Integration with HA notify services (Telegram, Discord, etc.)
- Email alerts
- SMS (via Twilio or similar)
- MQTT publish for other automation
- Siren/visual alerts (via HA entities)
- Smart display notifications (Google Home, Alexa)

#### Notification Rules
- Per-user notification preferences
- Severity-based filtering
- Do Not Disturb schedules
- Notification grouping/throttling

#### Home Assistant Notification Integration

**Notification Service Integration:**
- Leverage HA's `notify` service for multi-platform delivery
- Support all HA-configured notify platforms:
  - Mobile apps (iOS, Android)
  - Telegram
  - Discord
  - Pushover
  - Pushbullet
  - Slack
  - HTML5 push
  - And 50+ other integrations

**Actionable Notifications:**
- Code used: "View details" or "Dismiss"
- Alarm triggered: "Disarm", "View cameras", "Call police"
- Motion detected: "View camera snapshot", "Arm system"
- Door left open: "Close notification", "Bypass sensor"

**TTS Announcements:**
- Announce alarm state changes through smart speakers
- Entry/exit delay countdowns
- "Front door opened while armed away"
- "Guest code used by John's dog walker"
- Configurable voice and volume per event type

**Persistent Notifications:**
- Critical events stay in HA UI until acknowledged
- Alarm triggered events
- Failed arm attempts (sensor open)
- System errors or connection issues

**Mobile App Features:**
- Rich notifications with images (camera snapshots)
- Critical alerts (bypass Do Not Disturb)
- Location-aware notifications
- Notification history synced across devices

**Actionable Notification Callbacks:**
- Register webhook with Home Assistant for action callbacks
- Handle action responses asynchronously
- Support for:
  - Disarm system (requires code verification)
  - View cameras (return video stream URL)
  - Bypass sensor
  - Acknowledge alert
  - Execute custom automation
- Security: Validate webhook signature/token
- Log all actions taken via notifications

**Configurable State-Change Push Notifications (Phase 1–2)**
- Add a settings-driven option to push notifications to Home Assistant on selected alarm state changes.
- Supported “events” (initial):
  - Armed (per mode): `armed_home`, `armed_away`, `armed_night`, `armed_vacation`
  - `disarmed`
  - `pending` (entry delay started)
  - `triggered`
  - (Optional) `arming` (exit delay started) and `triggered_cleared` (disarm from triggered)
- Configuration knobs:
  - Enable/disable per state (or per transition: `from_state` → `to_state`).
  - Select HA notify target:
    - `notify.notify` (default) OR an explicit `notify.*` service (e.g. `notify.mobile_app_*`).
  - Message templates (simple): title/body per event; include variables like `to_state`, `from_state`, `timestamp`, `user_display_name`.
  - Throttling/cooldown per event type (avoid spam during flapping).
  - Optional “critical” flag for `triggered` (platform-dependent behavior).
- Delivery path:
  - On every state transition, emit an `AlarmEvent` (already a core requirement).
  - A background job (Celery) consumes state-change events and calls HA `notify` via the `HomeAssistantGateway`.
  - Failures should be non-blocking for the state transition (log + surface in system health).

**Example Notification Scenarios:**

*Code Usage:*
```yaml
Title: "Guest Code Used"
Message: "Dog Walker code used at Front Door"
Data:
  user: "Sarah (Dog Walker)"
  time: "2:30 PM"
  entry_point: "Front Door"
  code_type: "Temporary"
Actions:
  - action: "VIEW_HISTORY"
    title: "View History"
  - action: "DISMISS"
    title: "Dismiss"
Image: "https://alarm.local/api/camera/snapshot/front_door/latest.jpg"
Tag: "code_used_front_door"
```

*Alarm Triggered:*
```yaml
Title: "🚨 ALARM TRIGGERED"
Message: "Motion detected in Living Room"
Data:
  zone: "Living Room"
  trigger_time: "10:45 PM"
  armed_state: "Away"
  sensor: "motion.living_room"
Actions:
  - action: "DISARM"
    title: "Disarm"
    destructive: true
  - action: "VIEW_CAMERAS"
    title: "View Cameras"
  - action: "CALL_EMERGENCY"
    title: "Call Emergency"
    destructive: true
Priority: critical
TTS: "Alarm triggered. Motion detected in living room."
Sound: "alarm.wav"
```

*Entry Delay Active:*
```yaml
Title: "⏱️ Entry Delay Active"
Message: "Front door opened. 60 seconds to disarm."
Data:
  entry_point: "Front Door"
  time_remaining: 60
  armed_state: "Away"
Actions:
  - action: "QUICK_DISARM"
    title: "Disarm Now"
  - action: "EXTEND_DELAY"
    title: "Extend 30s"
Priority: high
TTS: "Entry delay active. 60 seconds to disarm."
Updates: true  # Update countdown in real-time
```

### 8. Automation & Rules Engine

#### Automation Triggers
- State changes (armed, disarmed, triggered)
- Sensor events (door, window, motion, etc.)
- Time-based schedules (specific time, sunrise/sunset, time range)
- **Person/Presence Detection:**
  - Person entity arrives home
  - Person entity leaves home
  - Last person leaves (auto-arm)
  - First person arrives (auto-disarm)
  - Specific person detection
  - Device tracker state changes
- Geofence enter/exit
- User actions (manual arm/disarm, code used)
- Failed code attempts
- Zone state changes
- HA entity state changes
- MQTT messages
- Webhook calls

#### Automation Actions
- Change alarm state
- Lock/unlock doors
- Send notifications
- Trigger HA scripts/automations
- Capture camera snapshot/clip
- Turn on lights
- Sound siren
- Call webhook

#### Pre-built Automations

**Presence-Based:**
- Auto-disarm when first person arrives home
- Auto-arm when last person leaves
- Auto-arm to "Away" when everyone leaves
- Disarm only for specific family members (not guests)
- Different arm states based on who's home
- Notification when person arrives/leaves while armed

**Time-Based:**
- Auto-arm at bedtime (e.g., 11 PM to "Night" mode)
- Auto-disarm in morning (e.g., 7 AM)
- Auto-arm weekdays at work time (e.g., 8 AM to "Away")
- Different schedules for weekdays vs weekends
- Vacation mode on calendar event
- Seasonal schedule adjustments (sunrise/sunset based)

**Sensor-Based:**
- Ignore motion sensors during certain hours (pet mode at night)
- Bypass garage sensor during trash day
- Enable extra sensors during vacation mode
- Disable outdoor sensors during storms/high wind
- Motion-activated lights when disarmed
- Camera recording on motion when armed

**State-Based:**
- Lock all doors when arming to "Away"
- Close garage door when arming
- Turn off lights when arming "Away"
- Set thermostat to away mode
- Enable pet mode sensors when armed "Home"
- Flash lights and sound siren on alarm

**Code-Based:**
- Unlock specific doors for specific codes (dog walker → back door only)
- Different actions for different users
- Notification to parents when kid arrives home (code used)
- Auto-enable guest code during scheduled visit
- Disable service codes outside scheduled hours

**Advanced:**
- Send camera snapshots when motion detected while armed
- Capture video clip on alarm trigger
- Call webhook to professional monitoring on alarm
- Gradually escalate alerts (notification → siren → call)
- Auto-bypass sensors if they fail health check
- Scene activation on arm/disarm states

#### Automation Conditions

Conditions allow fine-grained control over when automations execute:

**Time Conditions:**
- Specific time (exact time, sunrise/sunset)
- Time range (between 10 PM and 6 AM)
- Day of week (weekdays, weekends, specific days)
- Date range (vacation dates, seasonal)

**State Conditions:**
- Current alarm state
- Person presence (is anyone home?)
- Device tracker state
- Sensor state
- Weather conditions

**Logical Conditions:**
- AND (all conditions must be true)
- OR (any condition must be true)
- NOT (condition must be false)
- Nested conditions

#### Example Automation Configurations

**Auto-Arm When Last Person Leaves:**
```json
{
  "name": "Auto-arm when everyone leaves",
  "enabled": true,
  "triggers": [
    {
      "type": "ha_entity_state",
      "entity_id": "person.john",
      "from": "home",
      "to": "not_home"
    },
    {
      "type": "ha_entity_state",
      "entity_id": "person.jane",
      "from": "home",
      "to": "not_home"
    }
  ],
  "conditions": [
    {
      "type": "and",
      "conditions": [
        {
          "type": "ha_entity_state",
          "entity_id": "person.john",
          "state": "not_home"
        },
        {
          "type": "ha_entity_state",
          "entity_id": "person.jane",
          "state": "not_home"
        },
        {
          "type": "alarm_state",
          "state": "disarmed"
        }
      ]
    }
  ],
  "actions": [
    {
      "type": "arm_alarm",
      "state": "armed_away",
      "delay": 60
    },
    {
      "type": "lock_doors",
      "doors": "all"
    },
    {
      "type": "ha_notify",
      "service": "notify.mobile_app_iphone",
      "message": "Everyone left. Arming system in 60 seconds.",
      "data": {
        "actions": [
          {"action": "CANCEL_ARM", "title": "Cancel"}
        ]
      }
    }
  ]
}
```

**Auto-Disarm When First Person Arrives:**
```json
{
  "name": "Auto-disarm when first person arrives home",
  "enabled": true,
  "triggers": [
    {
      "type": "ha_entity_state",
      "entity_id": "person.john",
      "to": "home"
    },
    {
      "type": "ha_entity_state",
      "entity_id": "person.jane",
      "to": "home"
    }
  ],
  "conditions": [
    {
      "type": "or",
      "conditions": [
        {
          "type": "alarm_state",
          "state": "armed_away"
        },
        {
          "type": "alarm_state",
          "state": "armed_vacation"
        }
      ]
    }
  ],
  "actions": [
    {
      "type": "disarm_alarm"
    },
    {
      "type": "ha_notify",
      "service": "notify.notify",
      "message": "Welcome home! System disarmed."
    }
  ]
}
```

**Ignore Motion Sensors During Specific Hours:**
```json
{
  "name": "Bypass motion sensors at night (pet mode)",
  "enabled": true,
  "triggers": [
    {
      "type": "time",
      "at": "22:00:00"
    }
  ],
  "conditions": [
    {
      "type": "or",
      "conditions": [
        {
          "type": "alarm_state",
          "state": "armed_home"
        },
        {
          "type": "alarm_state",
          "state": "armed_night"
        }
      ]
    }
  ],
  "actions": [
    {
      "type": "bypass_sensors",
      "sensor_types": ["motion"],
      "zones": ["interior"],
      "until": "06:00:00"
    },
    {
      "type": "ha_notify",
      "service": "notify.notify",
      "message": "Pet mode activated. Interior motion sensors bypassed until 6 AM."
    }
  ]
}
```

**Arm to Night Mode at Bedtime (Weekdays Only):**
```json
{
  "name": "Auto-arm to Night mode at bedtime",
  "enabled": true,
  "triggers": [
    {
      "type": "time",
      "at": "23:00:00"
    }
  ],
  "conditions": [
    {
      "type": "and",
      "conditions": [
        {
          "type": "day_of_week",
          "days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
        },
        {
          "type": "alarm_state",
          "state": "disarmed"
        },
        {
          "type": "or",
          "conditions": [
            {
              "type": "ha_entity_state",
              "entity_id": "person.john",
              "state": "home"
            },
            {
              "type": "ha_entity_state",
              "entity_id": "person.jane",
              "state": "home"
            }
          ]
        }
      ]
    }
  ],
  "actions": [
    {
      "type": "arm_alarm",
      "state": "armed_night"
    },
    {
      "type": "lock_doors",
      "doors": "all"
    },
    {
      "type": "ha_service",
      "service": "light.turn_off",
      "entity_id": "light.downstairs"
    }
  ]
}
```

**Motion Alert with Camera Snapshot When Armed:**
```json
{
  "name": "Motion detected while armed - send snapshot",
  "enabled": true,
  "triggers": [
    {
      "type": "sensor_triggered",
      "sensor_type": "motion",
      "zones": ["living_room", "kitchen", "hallway"]
    }
  ],
  "conditions": [
    {
      "type": "and",
      "conditions": [
        {
          "type": "alarm_state",
          "states": ["armed_away", "armed_vacation"]
        },
        {
          "type": "time_range",
          "after": "08:00:00",
          "before": "18:00:00"
        }
      ]
    }
  ],
  "actions": [
    {
      "type": "capture_snapshot",
      "camera": "camera.living_room"
    },
    {
      "type": "ha_notify",
      "service": "notify.mobile_app_iphone",
      "message": "Motion detected at {{zone.name}} while armed!",
      "data": {
        "image": "{{snapshot_url}}",
        "actions": [
          {"action": "VIEW_CAMERAS", "title": "View Cameras"},
          {"action": "TRIGGER_ALARM", "title": "Trigger Alarm"}
        ]
      }
    },
    {
      "type": "delay",
      "seconds": 300
    },
    {
      "type": "ha_service",
      "service": "camera.record",
      "entity_id": "camera.living_room",
      "data": {
        "duration": 30
      }
    }
  ]
}
```

**Different Actions Based on Which Code Used:**
```json
{
  "name": "Dog walker code - unlock back door only",
  "enabled": true,
  "triggers": [
    {
      "type": "code_used",
      "code_name": "Dog Walker"
    }
  ],
  "conditions": [
    {
      "type": "time_range",
      "after": "10:00:00",
      "before": "16:00:00"
    }
  ],
  "actions": [
    {
      "type": "disarm_alarm"
    },
    {
      "type": "ha_service",
      "service": "lock.unlock",
      "entity_id": "lock.back_door"
    },
    {
      "type": "ha_notify",
      "service": "notify.mobile_app_parent",
      "message": "Dog walker arrived and unlocked back door."
    },
    {
      "type": "delay",
      "minutes": 60
    },
    {
      "type": "ha_service",
      "service": "lock.lock",
      "entity_id": "lock.back_door"
    },
    {
      "type": "ha_notify",
      "service": "notify.mobile_app_parent",
      "message": "Back door auto-locked after 1 hour."
    }
  ]
}
```

#### Automation Builder UI

**Visual Automation Editor:**
- Drag-and-drop trigger builder
- Visual condition builder with AND/OR/NOT logic
- Action sequence editor
- Template library for common automations
- Test mode to simulate automations
- Automation import/export (JSON)
- Duplicate and modify existing automations

**Automation Templates:**
Pre-built templates that users can customize:
1. "Auto-arm when leaving" - Select family members, delay time
2. "Auto-disarm when arriving" - Select family members, which states to disarm from
3. "Bedtime routine" - Select time, arm state, lock doors, turn off lights
4. "Pet mode at night" - Select sensors to bypass, time range
5. "Guest code activation" - Link to calendar, auto-enable/disable
6. "Vacation mode" - Link to calendar, extra security measures
7. "Service person access" - Code-based with time restrictions and specific door unlock
8. "Motion alerts with camera" - Select zones, notification preferences

**Smart Suggestions:**
- Analyze existing automations and suggest improvements
- Detect conflicting automations
- Suggest complementary automations (e.g., "You auto-arm when leaving, want to auto-disarm when arriving?")
- Learn from user patterns and suggest schedules

**Automation Groups:**
- Group related automations (e.g., "Vacation Mode" group)
- Enable/disable entire group at once
- Automation dependencies (automation A requires automation B)

### 9. Frigate Camera Integration

#### Person Detection
- Monitor Frigate events via MQTT or API
- Trigger actions on person detection
- Different responses based on alarm state
- Facial recognition integration (future)

#### Event Capture
- Automatic clip/snapshot saving
- Integration with Home Assistant media browser
- Timeline view of detections
- Person tracking across cameras

### 10. MQTT Integration

#### MQTT Features
- Subscribe to Home Assistant MQTT topics
- Publish alarm state changes
- Support for external keypads (via MQTT)
- Integration with Zigbee/Z-Wave bridges
- Custom MQTT event triggers

#### MQTT Topics Structure
```
alarm/state           # Current alarm state
alarm/command         # Arm/disarm commands
alarm/code/validate   # Code validation requests
alarm/event           # Alarm events
alarm/zone/{id}       # Individual zone states
```

### 11. Access Log & History

#### Logging
- Complete audit trail of all actions
- Code usage with timestamp and entry point
- State changes with reason
- Sensor triggers
- Failed access attempts
- System events

#### History View
- Searchable event log
- Filterable by date, user, event type
- Exportable (CSV, JSON)
- Retention policy configuration

### 12. Keypad Interface

#### Virtual Keypad
- Web-based keypad interface
- Mobile-responsive
- Arm/disarm with code
- Quick arm (no code required)
- Status display
- Countdown timers for entry/exit delay

#### Physical Keypad Support (MQTT)

**MQTT Topics for Keypad:**
```
alarm/keypad/{id}/code          # Keypad sends entered code
alarm/keypad/{id}/command       # Keypad sends arm/disarm command
alarm/keypad/{id}/state         # System sends current state to keypad
alarm/keypad/{id}/display       # System sends LCD message
alarm/keypad/{id}/beep          # System sends beep pattern
alarm/keypad/{id}/led           # System sends LED state (armed/ready/fault)
```

**Keypad Message Format:**
```json
{
  "code": "1234",
  "action": "disarm",
  "keypad_id": "front_door",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Supported Keypad Types:**
- ESP32/ESP8266 DIY keypads (Wiegand, matrix)
- Commercial keypads with MQTT bridge
- Zigbee keypads via Zigbee2MQTT (action events only; no code-based alarm control)
- Z-Wave keypads via zwavejs2mqtt

**Keypad Features:**
- Two-way communication (state sync)
- LCD/OLED display messages
- LED status indicators (armed, ready, fault)
- Audible feedback (beep patterns)
- Panic button support
- Tamper detection

### 13. Mobile & Responsive Design

#### Mobile Features
- Responsive web interface
- PWA support (installable)
- Quick arm/disarm widget
- Push notifications
- Location-based automation

### 14. Calendar Integration

#### Scheduling
- Temporary code scheduling
- Service personnel access windows
- Vacation mode scheduling
- Auto-state changes
- Integration with calendar services (Google, iCal)

---

## Additional Feature Ideas

### Advanced Features

1. **Video Verification**
   - View live camera feed before disarming from away
   - Automatic camera snapshots on alarm trigger
   - Clip compilation for events

2. **Geofencing**
   - Auto-disarm when approaching home
   - Auto-arm when everyone leaves
   - Integration with Home Assistant presence detection

3. **Voice Control**
   - Alexa/Google Home integration via HA
   - Voice arm/disarm with PIN
   - Status queries

4. **Panic/Duress Features**
   - Duress codes (appears to disarm but silently alerts)
   - Panic button integration
   - Medical alert integration

5. **Multi-Location Support**
   - Manage multiple properties
   - Per-property configurations
   - Centralized monitoring

6. **Integration Marketplace**
   - Plugin system for custom integrations
   - Community automation sharing
   - Pre-built scenes and modes

7. **Analytics & Insights**
   - Usage patterns
   - Most used entry points
   - Security score/recommendations
   - Sensor health monitoring

8. **Backup Monitoring**
   - Cellular backup notification (via HA)
   - Battery backup status
   - Offline mode operation

9. **Professional Monitoring Integration**
   - API for monitoring service integration
   - Automatic dispatch on alarm
   - Central station communication

10. **Smart Home Integration**
    - Scene activation on arm/disarm
    - Climate adjustments
    - Energy saving when armed away
    - Pet mode (disable motion on floor level)

11. **Weather Integration**
    - Storm mode (disable outdoor sensors)
    - Freeze alert monitoring
    - Severe weather notifications

12. **Maintenance Reminders**
    - Sensor battery replacement
    - System testing reminders
    - Firmware update notifications

### Operational & Resilience Enhancements

1. **Offline/HA-Down Resilience**
   - Cached entity states and queued commands when HA or network is unavailable
   - Health/heartbeat monitor with auto-failover to local-only alarms and siren/relay control
   - Optional isolated mode that keeps basic arming/disarming operational during outages

2. **Config & Change Management**
   - Versioned settings/profile history with rollback and audit trail
   - Export/import backups (YAML/JSON) plus validation before applying changes
   - Staging vs production configuration with sanity checks for dangerous edits

3. **Tamper & Safety**
   - Enclosure tamper input and sensor supervision (heartbeat/missing sensor detection)
   - RF/Zigbee jamming detection and alarms
   - Safe-mode arming when keypad/lock is offline and scheduled self-test routines

4. **Secrets & Critical Actions**
   - Hardware-backed secret storage (TPM/HSM) for HA tokens and alarm codes
   - WebAuthn/FIDO2 for admin-only or destructive actions
   - Signed/auditable logs with integrity checks

5. **Access Experience**
   - Guest/service check-in/out flows with instructions/notes
   - QR/NFC-based temporary access tokens
   - Time-bound one-time TOTP codes in addition to PINs

6. **Observability**
   - Metrics and OpenTelemetry traces for API, automation, and HA interactions
   - Anomaly detection on code usage/failures and unusual state changes
   - Alerting on missed heartbeats, failed arm attempts, or repeated sensor faults

7. **Operations Automation**
   - Maintenance mode to suppress alerts during servicing
   - Dry-run/simulation mode for automations and schedules
   - Practice alarm drills with automatic reset

8. **Hardware Integrations**
   - Local siren relay fallback independent of HA availability
   - Keypad LCD/LED messaging and status indicators
   - Battery/UPS monitoring with brownout behavior; optional LoRa/433MHz bridge

9. **Compliance & Readiness**
   - UL/EN50131-inspired readiness checklist
   - Data retention/PII minimization defaults and purge schedules
   - Incident runbooks for alarm triggers and false alarm workflows

---

## Database Schema

### Core Models

#### User
- Standard Django User model (extended)
- Role (admin, resident, guest, service)
- Phone number
- Notification preferences
- Active status
- 2FA settings

#### AlarmCode
- Code (encrypted)
- User (ForeignKey)
- Code type (permanent, temporary, one-time, duress)
- Valid from datetime
- Valid to datetime
- Days of week (JSON array)
- Time window start/end
- Max uses
- Current use count
- Is active
- Created/modified timestamps

#### AlarmState
- Current state (disarmed, home, away, night, vacation, triggered)
- Previous state
- Changed at timestamp
- Changed by (User)
- Changed via (code, web, automation, schedule)
- Entry delay seconds
- Exit delay seconds

#### Zone
- Name
- Type (entry, perimeter, interior, etc.)
- Entities (JSON array of HA entity IDs)
- Active in states (JSON array)
- Entry delay override
- Bypass until (datetime)
- Chime enabled
- Notification enabled

#### Event
- Timestamp
- Event type
- Severity (info, warning, critical)
- User (nullable)
- Zone (nullable)
- Entity (HA entity ID)
- Details (JSON)
- Acknowledged
- Archived

#### CodeUsage
- Alarm code (ForeignKey)
- Used at timestamp
- Entry point (Zone)
- Action (arm, disarm, unlock)
- Success boolean
- IP address
- User agent

#### Automation
- Name
- Description
- Enabled (boolean)
- Category (presence, time, sensor, state, code, advanced)
- Triggers (JSON array):
  ```json
  [{
    "type": "ha_entity_state|time|sensor_triggered|alarm_state|code_used|...",
    "entity_id": "person.john",
    "from": "home",
    "to": "not_home",
    ...
  }]
  ```
- Conditions (JSON array with support for AND/OR/NOT):
  ```json
  [{
    "type": "and|or|not",
    "conditions": [
      {"type": "alarm_state", "state": "disarmed"},
      {"type": "time_range", "after": "08:00", "before": "18:00"},
      {"type": "day_of_week", "days": ["monday", "tuesday"]},
      {"type": "ha_entity_state", "entity_id": "person.john", "state": "home"}
    ]
  }]
  ```
- Actions (JSON array):
  ```json
  [{
    "type": "arm_alarm|disarm_alarm|ha_notify|ha_service|lock_doors|...",
    "state": "armed_away",
    "delay": 60,
    ...
  }]
  ```
- Last triggered (datetime)
- Trigger count (integer)
- Last error (string, nullable)
- Created by (User)
- Created at timestamp
- Modified at timestamp

#### HomeAssistantEntity
- Entity ID
- Friendly name
- Entity type (sensor, lock, camera, etc.)
- Current state
- Last updated
- Zone assignment
- Configuration (JSON)

#### Notification
- User (ForeignKey)
- Event (ForeignKey)
- Channel (web, email, sms, ha_mobile, ha_persistent, ha_tts, telegram, discord, etc.)
- HA notify service (string, e.g., "notify.mobile_app_iphone")
- Sent at timestamp
- Delivered boolean
- Read boolean
- Acknowledged boolean
- Action taken (JSON - which action button was pressed)
- Notification data (JSON):
  - Title
  - Message
  - Priority
  - Image URL (camera snapshot)
  - Actions available
  - TTS message
- Retry count
- Error message (if failed)

#### UserNotificationPreference
- User (ForeignKey)
- Event type (alarm_triggered, code_used, state_changed, etc.)
- Enabled channels (JSON array: ["ha_mobile", "email", "ha_tts"])
- HA notify services (JSON array of service names)
- Priority threshold (info, warning, critical)
- Quiet hours start/end
- Include camera snapshot (boolean)
- TTS enabled (boolean)
- TTS message template (string)
- Actionable notifications enabled (boolean)
- Per-day schedule (JSON - different settings per day of week)

#### AlarmSettings
- Name (unique identifier for settings profile)
- Is active (boolean, only one can be active)
- Global settings:
  - Delay time (integer, seconds, default 60)
  - Arming time (integer, seconds, default 60)
  - Trigger time (integer, seconds, default 120)
  - Disarm after trigger (boolean, default false)
  - Code arm required (boolean, default true)
  - Available arming states (JSON array)
- Per-state overrides (JSON):
  ```json
  {
    "armed_away": {
      "delay_time": 90,
      "arming_time": 60,
      "trigger_time": 120
    },
    "armed_home": {
      "delay_time": 30,
      "arming_time": 30,
      "trigger_time": 90
    },
    "armed_night": {
      "delay_time": 15,
      "arming_time": 10,
      "trigger_time": 120
    },
    "armed_vacation": {
      "delay_time": 0,
      "arming_time": 60,
      "trigger_time": 300
    }
  }
  ```
- Audio/visual settings (JSON):
  - Beep enabled
  - Beep patterns
  - Countdown display enabled
  - Color coding enabled
- Sensor behavior settings (JSON):
  - Warn on open sensors
  - Auto bypass option
  - Force arm enabled
- Created at timestamp
- Modified at timestamp
- Modified by (User)

#### SystemConfig
- Key
- Value (JSON)
- Description
- Modified by (User)
- Modified at

#### ConfigVersion (for rollback/audit)
- Version number (auto-increment)
- Config type (alarm_settings, automation, zone, etc.)
- Config ID (ForeignKey to related model)
- Snapshot (JSON - full config at this version)
- Change description
- Created by (User)
- Created at timestamp
- Is current (boolean)

#### SystemHealth
- Component (ha_connection, mqtt, database, celery, redis)
- Status (healthy, degraded, offline)
- Last check timestamp
- Last healthy timestamp
- Error message (nullable)
- Metadata (JSON - latency, version info, etc.)

#### OfflineCache
- Entity ID (HA entity)
- Last known state
- Last updated from HA
- Pending commands (JSON array)
- Sync status (synced, pending, failed)

#### HardwareDevice
- Name
- Device type (siren_relay, keypad, ups, sensor_bridge)
- Connection type (gpio, mqtt, serial, network)
- Connection config (JSON)
- Status (online, offline, error)
- Last heartbeat
- Battery level (nullable)
- Firmware version (nullable)

#### MaintenanceWindow
- Name
- Start datetime
- End datetime
- Suppress notifications (boolean)
- Suppress automations (boolean)
- Suppress triggers (boolean)
- Created by (User)
- Notes

#### AlarmDrill
- Name
- Scheduled at (datetime)
- Started at (datetime, nullable)
- Completed at (datetime, nullable)
- Status (scheduled, in_progress, completed, cancelled)
- Drill type (full, silent, zone_test)
- Results (JSON - which sensors responded, timing)
- Created by (User)

#### AuditLog (immutable, signed)
- Timestamp
- Actor (User or system)
- Action type
- Target type (model name)
- Target ID
- Before state (JSON)
- After state (JSON)
- IP address
- User agent
- Signature (HMAC for integrity)
- Sequence number (for gap detection)

---

## API Design

### REST Endpoints

#### Authentication
- `POST /api/auth/login/` - Web login
- `POST /api/auth/logout/` - Logout
- `POST /api/auth/validate-code/` - Validate alarm code
- `POST /api/auth/2fa/verify/` - 2FA verification

#### Alarm Control
- `GET /api/alarm/state/` - Get current state
- `POST /api/alarm/arm/` - Arm system
- `POST /api/alarm/disarm/` - Disarm system
- `POST /api/alarm/trigger/` - Manual trigger (panic)
- `GET /api/alarm/zones/` - List zones
- `PATCH /api/alarm/zones/{id}/bypass/` - Bypass zone

#### Alarm Settings
- `GET /api/alarm/settings/` - Get active alarm settings
- `GET /api/alarm/settings/profiles/` - List all settings profiles
- `POST /api/alarm/settings/profiles/` - Create settings profile
- `GET /api/alarm/settings/profiles/{id}/` - Get specific profile
- `PATCH /api/alarm/settings/profiles/{id}/` - Update profile
- `DELETE /api/alarm/settings/profiles/{id}/` - Delete profile
- `POST /api/alarm/settings/profiles/{id}/activate/` - Set as active profile
- `GET /api/alarm/settings/timing/{state}/` - Get effective timing for specific state

#### User Management
- `GET /api/users/` - List users
- `POST /api/users/` - Create user
- `GET /api/users/{id}/` - User details
- `PATCH /api/users/{id}/` - Update user
- `DELETE /api/users/{id}/` - Delete user

#### Code Management
- `GET /api/codes/` - List codes
- `POST /api/codes/` - Create code
- `GET /api/codes/{id}/` - Code details
- `PATCH /api/codes/{id}/` - Update code
- `DELETE /api/codes/{id}/` - Delete code
- `GET /api/codes/{id}/usage/` - Code usage history

#### Events & History
- `GET /api/events/` - List events (paginated, filtered)
- `GET /api/events/{id}/` - Event details
- `PATCH /api/events/{id}/acknowledge/` - Acknowledge event
- `GET /api/events/export/` - Export events

#### Home Assistant
- `GET /api/ha/status/` - Connection status
- `POST /api/ha/discover/` - Discover entities
- `GET /api/ha/entities/` - List mapped entities
- `POST /api/ha/entities/{id}/command/` - Send command to entity

#### Automations
- `GET /api/automations/` - List automations
- `POST /api/automations/` - Create automation
- `GET /api/automations/{id}/` - Automation details
- `PATCH /api/automations/{id}/` - Update automation
- `DELETE /api/automations/{id}/` - Delete automation
- `POST /api/automations/{id}/trigger/` - Manual trigger

#### Notifications
- `GET /api/notifications/` - List user notifications
- `PATCH /api/notifications/{id}/read/` - Mark as read
- `PATCH /api/notifications/{id}/acknowledge/` - Acknowledge notification
- `POST /api/notifications/{id}/action/` - Handle actionable notification response
- `GET /api/notifications/preferences/` - Get all notification preferences
- `GET /api/notifications/preferences/{event_type}/` - Get preferences for event type
- `PATCH /api/notifications/preferences/{event_type}/` - Update preferences for event type
- `GET /api/notifications/ha-services/` - List available HA notify services
- `POST /api/notifications/test/` - Send test notification

#### System Health & Operations
- `GET /api/system/health/` - Overall system health status
- `GET /api/system/health/{component}/` - Specific component health
- `GET /api/system/diagnostics/` - Full diagnostic report
- `POST /api/system/test-connection/` - Test HA/MQTT connections

#### Maintenance & Drills
- `GET /api/maintenance/windows/` - List maintenance windows
- `POST /api/maintenance/windows/` - Create maintenance window
- `DELETE /api/maintenance/windows/{id}/` - Delete maintenance window
- `GET /api/maintenance/mode/` - Get current maintenance status
- `POST /api/maintenance/mode/` - Enter/exit maintenance mode
- `GET /api/drills/` - List alarm drills
- `POST /api/drills/` - Schedule a drill
- `POST /api/drills/{id}/start/` - Start a drill
- `POST /api/drills/{id}/cancel/` - Cancel a drill
- `GET /api/drills/{id}/results/` - Get drill results

#### Config Versioning
- `GET /api/config/versions/` - List config versions
- `GET /api/config/versions/{id}/` - Get specific version
- `POST /api/config/versions/{id}/rollback/` - Rollback to version
- `GET /api/config/versions/{id}/diff/` - Compare versions
- `POST /api/config/export/` - Export full config backup
- `POST /api/config/import/` - Import config backup (with validation)
- `POST /api/config/validate/` - Validate config without applying

#### Hardware Devices
- `GET /api/hardware/` - List hardware devices
- `POST /api/hardware/` - Register new device
- `GET /api/hardware/{id}/` - Device details
- `PATCH /api/hardware/{id}/` - Update device config
- `DELETE /api/hardware/{id}/` - Remove device
- `POST /api/hardware/{id}/test/` - Test device (trigger siren, etc.)
- `GET /api/hardware/{id}/status/` - Get device status

#### Audit Log
- `GET /api/audit/` - List audit entries (paginated)
- `GET /api/audit/export/` - Export audit log
- `GET /api/audit/verify/` - Verify log integrity

### WebSocket Endpoints

- `/ws/alarm/` - Real-time alarm state updates
- `/ws/events/` - Real-time event stream
- `/ws/zones/` - Zone status updates
- `/ws/health/` - System health updates

#### WebSocket Protocol
```json
{
  "type": "alarm_state|event|zone_update|health|countdown",
  "timestamp": "2024-01-15T10:30:00Z",
  "payload": { ... },
  "sequence": 12345
}
```

#### WebSocket Authentication
- Token-based auth via query param or first message
- Automatic reconnection with exponential backoff
- Heartbeat/ping-pong for connection health
- Message queue for offline periods (short buffer)

---

## Background Tasks (Celery)

### Periodic Tasks
- **Health Check** (every 30s): Monitor HA, MQTT, hardware connections
- **Entity Sync** (every 60s): Sync entity states from HA to cache
- **Code Cleanup** (daily): Expire and remove old temporary codes
- **Event Archival** (daily): Archive old events per retention policy
- **Notification Retry** (every 5m): Retry failed notifications
- **Automation Scheduler** (every 1m): Check time-based automation triggers
- **Hardware Heartbeat** (every 30s): Check hardware device health
- **Audit Log Integrity** (hourly): Verify audit log signatures

### On-Demand Tasks
- `send_notification`: Send notification via specified channel
- `execute_automation`: Run automation actions
- `sync_ha_entities`: Full entity discovery and sync
- `capture_camera_snapshot`: Get snapshot from Frigate/camera
- `trigger_siren`: Activate siren with timeout
- `send_ha_command`: Execute HA service call
- `process_mqtt_message`: Handle incoming MQTT messages
- `run_drill`: Execute alarm drill sequence
- `export_audit_log`: Generate audit log export
- `import_config`: Validate and apply config import

### Task Configuration
```python
CELERY_BEAT_SCHEDULE = {
    'health-check': {'task': 'alarm.tasks.health_check', 'schedule': 30.0},
    'entity-sync': {'task': 'alarm.tasks.sync_entities', 'schedule': 60.0},
    'code-cleanup': {'task': 'alarm.tasks.cleanup_codes', 'schedule': crontab(hour=3)},
    'event-archival': {'task': 'alarm.tasks.archive_events', 'schedule': crontab(hour=4)},
}
```

### Task Retry Strategy
- Notifications: 3 retries with exponential backoff (1m, 5m, 15m)
- HA commands: 5 retries with 10s intervals
- Critical tasks (siren, alarm): No retry limit, immediate retry

---

## Error Handling & Resilience

### HA Connection Failure
1. Mark HA status as degraded
2. Switch to cached entity states
3. Queue outgoing commands for retry
4. Continue basic arm/disarm with local state
5. Trigger local siren relay if alarm triggers
6. Notify admins of connection loss
7. Auto-reconnect with backoff (1s, 2s, 4s... max 60s)

### MQTT Connection Failure
1. Mark MQTT status as degraded
2. Buffer outgoing messages (limited queue)
3. Continue without MQTT-based devices
4. Reconnect with backoff
5. Replay buffered messages on reconnect

### Notification Failure
1. Log failure with error details
2. Queue for retry (max 3 attempts)
3. Try fallback channels (email → SMS → HA push)
4. Mark as failed after all retries exhausted
5. Critical alerts: Continue trying indefinitely

### Database Failure
1. Return cached responses where possible
2. Queue writes for retry
3. Alarm operations continue with in-memory state
4. Alert admins immediately
5. Graceful degradation of non-critical features

### Automation Failure
1. Log error with full context
2. Mark automation as errored
3. Continue with other automations
4. Notify admin if critical automation fails
5. Circuit breaker: Disable after repeated failures

### State Recovery
- On startup: Load last known state from database
- Verify state with HA entities
- Reconcile any discrepancies
- Log state recovery actions
- Resume pending automations/timers

---

## Security Considerations

### Authentication & Authorization
- HTTPS only in production
- Secure session management
- CSRF protection
- Rate limiting on auth endpoints
- Account lockout after failed attempts
- Secure code storage (hashed/encrypted)
- API key authentication for integrations

### Data Protection
- Encrypt alarm codes at rest
- Encrypt sensitive configuration
- Secure environment variable management
- Regular security audits
- SQL injection prevention (Django ORM)
- XSS prevention

### Network Security
- Firewall recommendations
- VPN access option
- Local network restriction options
- MQTT authentication
- TLS for MQTT

### Audit & Compliance
- Comprehensive logging
- Tamper detection
- Data retention policies
- GDPR compliance considerations
- Export user data capability

---

## Implementation Phases

### Phase 1: Foundation (MVP)
- Django project setup
- User authentication
- Basic alarm states (disarm, arm home, arm away)
- Alarm settings management (timing, delays, behavior)
- Entry/exit delay countdowns
- Home Assistant connection
- Simple sensor monitoring
- Basic web interface
- Permanent code management
- State-specific timing overrides

### Phase 2: Core Features
- Zone management
- Temporary codes with time restrictions
- Event logging
- Notification system (basic)
- Entry/exit delays
- Lock integration
- Mobile responsive design

### Phase 3: Advanced Integration
- MQTT integration
- Frigate person detection
- Automation engine
- Advanced notifications (email, SMS, push)
- Code usage tracking
- Calendar integration
- WebSocket real-time updates

### Phase 4: Enhanced Features
- Geofencing
- Video verification
- Voice control integration
- Analytics dashboard
- Advanced automation rules
- Duress codes
- Multi-zone management

### Phase 5: Resilience & Operations
- Offline mode / HA-down resilience
- Config versioning and rollback
- Hardware device integrations (siren relay, UPS)
- Maintenance mode and drills
- System health monitoring
- Audit log with integrity checks

### Phase 6: Polish & Extras
- PWA support
- Advanced reporting and analytics
- Multi-location support
- Plugin system
- Professional monitoring API
- Accessibility improvements (a11y)
- Internationalization (i18n)
- Mobile app (optional)

---

## Configuration

### Environment Variables

```bash
# Django
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=

# Database
DATABASE_URL=postgresql://user:pass@localhost/alarm_db

# Redis
REDIS_URL=redis://localhost:6379/0

# Integrations
# Home Assistant / MQTT / Z-Wave JS / etc are configured in the UI (active settings profile).

# Frigate (optional)
FRIGATE_URL=http://frigate.local:5000

# Notifications are configured in the UI.

# Security
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
```

### Initial Setup Process

1. Clone repository
2. Create `.env` file with configuration
3. Run migrations: `python manage.py migrate`
4. Create superuser (first user setup wizard will trigger)
5. Configure Home Assistant connection
6. Configure alarm settings (timing, behavior, etc.)
7. Discover and map entities
8. Configure zones
9. Set up automations
10. Configure notifications

### Default Alarm Settings Profile

The system will create a default settings profile on first run with these values:

```json
{
  "name": "Default",
  "is_active": true,
  "delay_time": 60,
  "arming_time": 60,
  "trigger_time": 120,
  "disarm_after_trigger": false,
  "code_arm_required": true,
  "available_arming_states": [
    "armed_away",
    "armed_home",
    "armed_night",
    "armed_vacation"
  ],
  "state_overrides": {},
  "audio_visual_settings": {
    "beep_enabled": true,
    "countdown_display_enabled": true,
    "color_coding_enabled": true
  },
  "sensor_behavior": {
    "warn_on_open_sensors": true,
    "auto_bypass_enabled": false,
    "force_arm_enabled": true
  }
}
```

### Example Settings Profiles

**Quick Response Profile** (For occupied homes with pets)
```json
{
  "name": "Quick Response",
  "delay_time": 30,
  "arming_time": 45,
  "state_overrides": {
    "armed_home": {
      "delay_time": 20,
      "arming_time": 30
    },
    "armed_night": {
      "delay_time": 10,
      "arming_time": 15
    }
  }
}
```

**Maximum Security Profile** (For vacation/unoccupied)
```json
{
  "name": "Maximum Security",
  "delay_time": 0,
  "arming_time": 90,
  "trigger_time": 300,
  "code_arm_required": true,
  "state_overrides": {
    "armed_vacation": {
      "delay_time": 0,
      "arming_time": 60,
      "trigger_time": 300
    }
  }
}
```

---

## Testing Strategy

### Unit Tests
- Model validation
- Code validation logic
- Time window checking
- State transitions
- Permission checks
- Alarm settings validation
- Timing calculations (delay, arming, trigger)
- Per-state override resolution
- Code requirement enforcement
- Available states filtering

### Integration Tests
- Home Assistant API communication
- MQTT messaging
- Notification delivery
- Automation execution
- WebSocket communication

### E2E Tests
- User onboarding flow
- Arm/disarm cycles with delays
- Entry delay countdown and disarm
- Exit delay countdown and auto-arm
- Code creation and usage
- Alarm trigger scenarios
- Trigger timeout behavior (return to previous state vs auto-disarm)
- Multi-user scenarios
- Settings profile switching
- Per-state timing override behavior
- Force arm with open sensors
- Quick arm (no code) functionality

---

## Deployment

### Recommended Stack
- **Web Server**: Nginx
- **WSGI Server**: Gunicorn
- **WebSocket**: Daphne (for Channels)
- **Process Manager**: Supervisor or systemd
- **Task Queue**: Celery workers
- **Database**: PostgreSQL
- **Cache**: Redis

### Docker Support

**Container Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                    docker-compose                        │
├─────────────┬─────────────┬─────────────┬───────────────┤
│   nginx     │   django    │   celery    │  celery-beat  │
│   (proxy)   │   (web)     │  (worker)   │  (scheduler)  │
├─────────────┴─────────────┴─────────────┴───────────────┤
│                     redis                                │
├─────────────────────────────────────────────────────────┤
│                   postgresql                             │
└─────────────────────────────────────────────────────────┘
```

**docker-compose.yml services:**
- `web`: Django + Gunicorn + Daphne (HTTP + WebSocket)
- `celery`: Celery worker for background tasks
- `celery-beat`: Celery scheduler for periodic tasks
- `redis`: Cache + message broker + pub/sub
- `postgres`: Database
- `nginx`: Reverse proxy (optional, for SSL termination)

**Dockerfile (multi-stage):**
```dockerfile
# Build stage
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Production stage
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=frontend /app/frontend/dist ./static/
COPY . .
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
```

**Volume Mounts:**
- `/app/data` - SQLite fallback, file uploads
- `/app/logs` - Application logs
- `/app/backups` - Config backups

**Health Checks:**
- `/api/health/` - Overall system health
- `/api/health/db/` - Database connectivity
- `/api/health/redis/` - Redis connectivity
- `/api/health/ha/` - Home Assistant connection

**Environment Variables (Docker):**
```yaml
environment:
  - SECRET_KEY=${SECRET_KEY}
  - DATABASE_URL=postgresql://alarm:${DB_PASSWORD}@postgres:5432/alarm
  - REDIS_URL=redis://redis:6379/0
  # Integration settings (Home Assistant/MQTT/etc) are configured in the UI.
```

### Monitoring
- Application logging (structured logs)
- Error tracking (Sentry)
- Performance monitoring
- Home Assistant connection health
- Queue monitoring (Celery)

---

## Future Considerations

1. **Machine Learning**
   - Pattern detection for unusual activity
   - False alarm reduction
   - Predictive maintenance

2. **Blockchain Integration**
   - Immutable audit log
   - Distributed verification

3. **Professional Features**
   - Central station monitoring
   - UL-compliant features
   - Insurance integration

4. **Smart Integrations**
   - Ring/Nest integration
   - Vehicle detection
   - Package delivery detection

5. **Advanced Analytics**
   - Security scoring
   - Recommendations engine
   - Energy impact reporting

---

## Resources & Documentation

### Development
- Django documentation
- Django REST Framework
- Django Channels
- Home Assistant API docs
- Frigate API docs
- MQTT protocol specs

### Libraries
- `homeassistant-api` - HA Python client
- `paho-mqtt` - MQTT client
- `celery` - Task queue
- `channels` - WebSocket support
- `django-cors-headers` - CORS handling
- `djangorestframework` - API framework
- `django-environ` - Environment config
- `python-jose` - JWT handling

---

## License

TBD (Consider MIT or Apache 2.0 for open source)

---

## Contributors

TBD

---

## Risks & Open Questions

### Technical Risks

1. **HA WebSocket Stability**
   - HA WebSocket can disconnect; need robust reconnection
   - Consider polling fallback for critical state sync
   - Test under various network conditions

2. **Real-time Latency**
   - Alarm state changes must be near-instantaneous
   - Entry delay countdown needs sub-second accuracy
   - Consider using Redis pub/sub for internal events

3. **Database Performance**
   - Event logging could grow large quickly
   - Need indexing strategy for common queries
   - Consider TimescaleDB for time-series event data
   - Implement archival/purge policies early

4. **State Consistency**
   - Multiple sources of truth (HA, local DB, cache)
   - Race conditions during arm/disarm
   - Need clear state machine with atomic transitions

5. **Security Surface**
   - Web-accessible alarm system is inherently risky
   - Consider VPN-only access option
   - Rate limiting and brute force protection critical
   - Code hashing must be secure (Argon2/bcrypt)

### Decisions Made

1. **Deployment Model**: Dockerized
   - Runs anywhere via Docker/docker-compose
   - HA URL configured via environment variable
   - Can run on same host as HA or separate hardware
   - No dependency on HA host availability for basic functions

2. **HA Integration**: Standalone App
   - No companion HA custom component
   - Communicates via HA REST API and WebSocket
   - Uses HA's native notify services for notifications
   - Independent operation when HA is unavailable

3. **Code Entry Method**: MQTT Keypad
   - Primary: Web/mobile interface
   - Physical keypad support via MQTT
   - Smart lock keypad codes synced where supported

4. **Database**: PostgreSQL
   - Standard PostgreSQL for all data
   - Event archival via retention policies
   - No TimescaleDB complexity needed initially

### Open Questions

1. **Professional Monitoring**
   - Which monitoring services to integrate?
   - SIA/Contact ID protocol support?
   - Self-hosted vs cloud monitoring API?

2. **Multi-tenant vs Single-tenant**
   - Design for single household initially
   - Consider multi-tenant in future phases?

3. **Licensing & Liability**
   - Open source license choice (MIT, Apache, GPL)?
   - Disclaimer for security-critical application
   - No warranty clause

### Performance Targets

| Operation | Target Latency |
|-----------|---------------|
| Arm/Disarm | < 500ms |
| Entry delay start | < 100ms |
| Alarm trigger | < 200ms |
| Notification send | < 2s |
| Dashboard load | < 1s |
| WebSocket update | < 100ms |

### Capacity Targets

| Metric | Initial Target |
|--------|---------------|
| Concurrent users | 10 |
| Sensors/zones | 100 |
| Events/day | 10,000 |
| Automations | 50 |
| Codes | 100 |
| Event retention | 90 days |

---

## Notes

This planning document is a living document and should be updated as the project evolves. Features may be added, modified, or removed based on user feedback and technical constraints.
