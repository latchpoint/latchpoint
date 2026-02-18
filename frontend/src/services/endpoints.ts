// Central place to keep frontend API/WS paths consistent.

export const apiEndpoints = {
  auth: {
    csrf: '/api/auth/csrf/',
    login: '/api/auth/login/',
    logout: '/api/auth/logout/',
    verify2FA: '/api/auth/2fa/verify/',
    validateCode: '/api/auth/validate-code/',
  },
  users: {
    me: '/api/users/me/',
    all: '/api/users/',
  },
  onboarding: {
    base: '/api/onboarding/',
    setupStatus: '/api/onboarding/setup-status/',
  },
  alarm: {
    state: '/api/alarm/state/',
    arm: '/api/alarm/arm/',
    disarm: '/api/alarm/disarm/',
    cancelArming: '/api/alarm/cancel-arming/',
    trigger: '/api/alarm/trigger/',
    settings: '/api/alarm/settings/',
    settingsProfiles: '/api/alarm/settings/profiles/',
    settingsProfile: (id: number) => `/api/alarm/settings/profiles/${id}/`,
    activateSettingsProfile: (id: number) => `/api/alarm/settings/profiles/${id}/activate/`,
  },
  events: {
    all: '/api/events/',
    acknowledge: (id: number) => `/api/events/${id}/acknowledge/`,
  },
  sensors: {
    all: '/api/alarm/sensors/',
    detail: (id: number) => `/api/alarm/sensors/${id}/`,
  },
  entities: {
    all: '/api/alarm/entities/',
    sync: '/api/alarm/entities/sync/',
  },
  rules: {
    all: '/api/alarm/rules/',
    detail: (id: number) => `/api/alarm/rules/${id}/`,
    run: '/api/alarm/rules/run/',
    simulate: '/api/alarm/rules/simulate/',
  },
  codes: {
    all: '/api/codes/',
    detail: (id: number) => `/api/codes/${id}/`,
    usage: (id: number) => `/api/codes/${id}/usage/`,
  },
  doorCodes: {
    all: '/api/door-codes/',
    detail: (id: number) => `/api/door-codes/${id}/`,
  },
  controlPanels: {
    all: '/api/control-panels/',
    detail: (id: number) => `/api/control-panels/${id}/`,
    test: (id: number) => `/api/control-panels/${id}/test/`,
  },
  locks: {
    available: '/api/locks/available/',
    syncConfig: (lockEntityId: string) => `/api/locks/${encodeURIComponent(lockEntityId)}/sync-config/`,
    dismissedAssignments: (lockEntityId: string) => `/api/locks/${encodeURIComponent(lockEntityId)}/dismissed-assignments/`,
  },
  doorCodeAssignments: {
    undismiss: (assignmentId: number) => `/api/door-code-assignments/${assignmentId}/undismiss/`,
  },
  systemConfig: {
    all: '/api/system-config/',
    key: (key: string) => `/api/system-config/${encodeURIComponent(key)}/`,
  },
  debug: {
    logs: '/api/alarm/debug/logs/',
  },
  scheduler: {
    status: '/api/scheduler/status/',
    taskRuns: (taskName: string) =>
      `/api/scheduler/tasks/${encodeURIComponent(taskName)}/runs/`,
  },
  homeAssistant: {
    status: '/api/alarm/home-assistant/status/',
    settings: '/api/alarm/home-assistant/settings/',
    entities: '/api/alarm/home-assistant/entities/',
    notifyServices: '/api/alarm/home-assistant/notify-services/',
  },
  mqtt: {
    status: '/api/alarm/mqtt/status/',
    settings: '/api/alarm/mqtt/settings/',
    test: '/api/alarm/mqtt/test/',
  },
  notifications: {
    providers: '/api/notifications/providers/',
    provider: (id: string) => `/api/notifications/providers/${id}/`,
    testProvider: (id: string) => `/api/notifications/providers/${id}/test/`,
    providerTypes: '/api/notifications/provider-types/',
    pushbulletDevices: '/api/notifications/pushbullet/devices/',
    pushbulletValidateToken: '/api/notifications/pushbullet/validate-token/',
  },
  integrations: {
    homeAssistantMqttAlarmEntity: {
      settings: '/api/alarm/integrations/home-assistant/mqtt-alarm-entity/',
      status: '/api/alarm/integrations/home-assistant/mqtt-alarm-entity/status/',
      publishDiscovery: '/api/alarm/integrations/home-assistant/mqtt-alarm-entity/publish-discovery/',
    },
    zwavejs: {
      status: '/api/alarm/zwavejs/status/',
      nodes: '/api/alarm/zwavejs/nodes/',
      settings: '/api/alarm/zwavejs/settings/',
      test: '/api/alarm/zwavejs/test/',
      syncEntities: '/api/alarm/zwavejs/entities/sync/',
    },
    zigbee2mqtt: {
      status: '/api/alarm/integrations/zigbee2mqtt/status/',
      settings: '/api/alarm/integrations/zigbee2mqtt/settings/',
      devices: '/api/alarm/integrations/zigbee2mqtt/devices/',
      syncDevices: '/api/alarm/integrations/zigbee2mqtt/devices/sync/',
    },
    frigate: {
      status: '/api/alarm/integrations/frigate/status/',
      settings: '/api/alarm/integrations/frigate/settings/',
      options: '/api/alarm/integrations/frigate/options/',
      detections: '/api/alarm/integrations/frigate/detections/',
      detection: (id: number) => `/api/alarm/integrations/frigate/detections/${id}/`,
    },
  },
} as const

export const wsEndpoints = {
  alarm: '/ws/alarm/',
} as const
