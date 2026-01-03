export interface HomeAssistantMqttAlarmEntitySettings {
  enabled: boolean
  entityName: string
  alsoRenameInHomeAssistant: boolean
  haEntityId: string
}

export interface HomeAssistantMqttAlarmEntitySettingsUpdate {
  enabled?: boolean
  entityName?: string
  alsoRenameInHomeAssistant?: boolean
  haEntityId?: string
}

export interface HomeAssistantMqttAlarmEntityStatus {
  lastDiscoveryPublishAt: string | null
  lastStatePublishAt: string | null
  lastAvailabilityPublishAt: string | null
  lastErrorAt: string | null
  lastError: string | null
}

export interface HomeAssistantMqttAlarmEntityStatusResponse {
  settings: HomeAssistantMqttAlarmEntitySettings
  status: HomeAssistantMqttAlarmEntityStatus
}

