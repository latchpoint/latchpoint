import type { MqttStatus } from './mqtt'

export interface FrigateSettings {
  enabled: boolean
  eventsTopic: string
  retentionSeconds: number
  runRulesOnEvent: boolean
  runRulesDebounceSeconds: number
  runRulesMaxPerMinute: number
  runRulesKinds?: string[]
  knownCameras?: string[]
  knownZonesByCamera?: Record<string, string[]>
}

export interface FrigateSettingsUpdate {
  enabled?: boolean
  eventsTopic?: string
  retentionSeconds?: number
  runRulesOnEvent?: boolean
  runRulesDebounceSeconds?: number
  runRulesMaxPerMinute?: number
  runRulesKinds?: string[]
  knownCameras?: string[]
  knownZonesByCamera?: Record<string, string[]>
}

export interface FrigateStatus {
  enabled: boolean
  eventsTopic: string
  retentionSeconds: number
  available: boolean
  mqtt: MqttStatus
  ingest: {
    lastIngestAt: string | null
    lastError: string | null
  }
  rulesRun?: {
    lastRulesRunAt: string | null
    triggered: number
    skippedDebounce: number
    skippedRateLimit: number
  }
}

export interface FrigateOptions {
  cameras: string[]
  zonesByCamera: Record<string, string[]>
}

export interface FrigateDetection {
  id: number
  eventId: string
  camera: string
  zones: unknown
  confidencePct: number
  observedAt: string
}

export interface FrigateDetectionDetail {
  id: number
  eventId: string
  provider: string
  label: string
  camera: string
  zones: unknown
  confidencePct: number
  observedAt: string
  sourceTopic: string
  createdAt: string
  updatedAt: string
  raw: Record<string, unknown>
}
