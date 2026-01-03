// API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_URL || ''
export const WS_BASE_URL = import.meta.env.VITE_WS_URL || API_BASE_URL

// Common HTTP/WS config
export const CSRF_COOKIE_NAME = 'csrftoken'
export const CSRF_HEADER_NAME = 'X-CSRFToken'

// Time constants (ms)
export const SECOND_MS = 1000
export const FIVE_SECONDS_MS = 5_000
export const TEN_SECONDS_MS = 10_000
export const THIRTY_SECONDS_MS = 30_000
export const ONE_MINUTE_MS = 60_000

// UI defaults
export const DEFAULT_RECENT_EVENTS_LIMIT = 10

// Alarm States
export const AlarmState = {
  DISARMED: 'disarmed',
  ARMING: 'arming',
  ARMED_HOME: 'armed_home',
  ARMED_AWAY: 'armed_away',
  ARMED_NIGHT: 'armed_night',
  ARMED_VACATION: 'armed_vacation',
  ARMED_CUSTOM_BYPASS: 'armed_custom_bypass',
  PENDING: 'pending',
  TRIGGERED: 'triggered',
} as const

export type AlarmStateType = (typeof AlarmState)[keyof typeof AlarmState]

// Alarm State Labels
export const AlarmStateLabels: Record<AlarmStateType, string> = {
  [AlarmState.DISARMED]: 'Disarmed',
  [AlarmState.ARMING]: 'Arming',
  [AlarmState.ARMED_HOME]: 'Armed Home',
  [AlarmState.ARMED_AWAY]: 'Armed Away',
  [AlarmState.ARMED_NIGHT]: 'Armed Night',
  [AlarmState.ARMED_VACATION]: 'Armed Vacation',
  [AlarmState.ARMED_CUSTOM_BYPASS]: 'Armed (Custom Bypass)',
  [AlarmState.PENDING]: 'Entry Delay',
  [AlarmState.TRIGGERED]: 'TRIGGERED',
}

// Alarm State Colors (Tailwind classes)
export const AlarmStateColors: Record<AlarmStateType, string> = {
  [AlarmState.DISARMED]: 'bg-alarm-disarmed',
  [AlarmState.ARMING]: 'bg-alarm-arming',
  [AlarmState.ARMED_HOME]: 'bg-alarm-armed-home',
  [AlarmState.ARMED_AWAY]: 'bg-alarm-armed-away',
  [AlarmState.ARMED_NIGHT]: 'bg-alarm-armed-night',
  [AlarmState.ARMED_VACATION]: 'bg-alarm-armed-vacation',
  [AlarmState.ARMED_CUSTOM_BYPASS]: 'bg-alarm-armed-away',
  [AlarmState.PENDING]: 'bg-alarm-pending',
  [AlarmState.TRIGGERED]: 'bg-alarm-triggered',
}

// User Roles
export const UserRole = {
  ADMIN: 'admin',
  RESIDENT: 'resident',
  GUEST: 'guest',
  SERVICE: 'service',
} as const

export type UserRoleType = (typeof UserRole)[keyof typeof UserRole]

// Event Types
export const EventType = {
  ARMED: 'armed',
  DISARMED: 'disarmed',
  PENDING: 'pending',
  TRIGGERED: 'triggered',
  CODE_USED: 'code_used',
  SENSOR_TRIGGERED: 'sensor_triggered',
  FAILED_CODE: 'failed_code',
  STATE_CHANGED: 'state_changed',
} as const

export type EventTypeType = (typeof EventType)[keyof typeof EventType]

// Routes
export const Routes = {
  HOME: '/',
  ONBOARDING: '/onboarding',
  LOGIN: '/login',
  SETUP: '/setup',
  SETUP_MQTT: '/setup/mqtt',
  SETUP_ZWAVEJS: '/setup/zwavejs',
  SETUP_IMPORT_SENSORS: '/setup/import-sensors',
  DASHBOARD: '/dashboard',
  RULES: '/rules',
  RULES_TEST: '/rules/test',
  CODES: '/alarm-codes',
  DOOR_CODES: '/door-codes',
  EVENTS: '/events',
  CONTROL_PANELS: '/control-panels',
  SETTINGS: '/settings',
} as const

// Local Storage Keys
export const StorageKeys = {
  AUTH_TOKEN: 'alarm_auth_token',
  REFRESH_TOKEN: 'alarm_refresh_token',
  THEME: 'alarm_theme',
  RULES_TEST_SCENARIOS: 'alarm_rules_test_scenarios',
} as const

// Notification Providers
// Special ID for the Home Assistant system provider (auto-created when HA is configured)
export const HA_SYSTEM_PROVIDER_ID = 'ha-system-provider'
