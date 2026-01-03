// Generic API Response Wrappers

export interface ApiResponse<T> {
  data: T
  message?: string
}

export interface ApiError {
  message: string
  code?: string
  errorCode?: string
  gateway?: string
  operation?: string
  error?: string
  details?: Record<string, string[]>
}

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  pageSize: number
  totalPages: number
  hasNext: boolean
  hasPrevious: boolean
}

export interface PaginationParams {
  page?: number
  pageSize?: number
  ordering?: string
}

// Health Check Response
export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'offline'
  components: {
    database: ComponentHealth
    redis: ComponentHealth
    homeAssistant: ComponentHealth
    mqtt?: ComponentHealth
    celery: ComponentHealth
  }
  timestamp: string
}

export interface ComponentHealth {
  status: 'healthy' | 'degraded' | 'offline'
  lastCheck: string
  latency?: number
  error?: string
}

// WebSocket Status
export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

// Query Keys for React Query
export const queryKeys = {
  alarm: {
    state: ['alarm', 'state'] as const,
    settings: ['alarm', 'settings'] as const,
    settingsProfiles: ['alarm', 'settings', 'profiles'] as const,
    countdown: ['alarm', 'countdown'] as const,
  },
  entities: {
    all: ['entities'] as const,
  },
  rules: {
    all: ['rules'] as const,
  },
  sensors: {
    all: ['sensors'] as const,
    detail: (id: number) => ['sensors', id] as const,
  },
  codes: {
    all: ['codes'] as const,
    byUser: (userId: string) => ['codes', 'byUser', userId] as const,
    detail: (id: number) => ['codes', id] as const,
    usage: (id: number) => ['codes', id, 'usage'] as const,
  },
  doorCodes: {
    all: ['doorCodes'] as const,
    byUser: (userId: string) => ['doorCodes', 'byUser', userId] as const,
    detail: (id: number) => ['doorCodes', id] as const,
  },
  events: {
    all: ['events'] as const,
    recent: ['events', 'recent'] as const,
  },
  systemConfig: {
    all: ['systemConfig'] as const,
  },
  users: {
    all: ['users'] as const,
    current: ['users', 'current'] as const,
    detail: (id: number) => ['users', id] as const,
  },
  health: ['health'] as const,
  homeAssistant: {
    status: ['homeAssistant', 'status'] as const,
    settings: ['homeAssistant', 'settings'] as const,
    entities: ['homeAssistant', 'entities'] as const,
    notifyServices: ['homeAssistant', 'notifyServices'] as const,
  },
  websocket: {
    status: ['websocket', 'status'] as const,
  },
  mqtt: {
    status: ['mqtt', 'status'] as const,
    settings: ['mqtt', 'settings'] as const,
  },
  integrations: {
    homeAssistantMqttAlarmEntity: ['integrations', 'homeAssistant', 'mqttAlarmEntity'] as const,
    homeAssistantMqttAlarmEntityStatus: ['integrations', 'homeAssistant', 'mqttAlarmEntity', 'status'] as const,
  },
  zwavejs: {
    status: ['zwavejs', 'status'] as const,
    settings: ['zwavejs', 'settings'] as const,
    nodes: ['zwavejs', 'nodes'] as const,
  },
  zigbee2mqtt: {
    status: ['zigbee2mqtt', 'status'] as const,
    settings: ['zigbee2mqtt', 'settings'] as const,
    devices: ['zigbee2mqtt', 'devices'] as const,
  },
  controlPanels: {
    all: ['controlPanels'] as const,
  },
  frigate: {
    status: ['frigate', 'status'] as const,
    settings: ['frigate', 'settings'] as const,
    options: ['frigate', 'options'] as const,
    detections: ['frigate', 'detections'] as const,
  },
  onboarding: {
    status: ['onboarding', 'status'] as const,
    setupStatus: ['onboarding', 'setupStatus'] as const,
  },
  auth: {
    session: ['auth', 'session'] as const,
    currentUser: ['auth', 'currentUser'] as const,
  },
}
