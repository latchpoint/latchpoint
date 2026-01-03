export type SystemConfigValueType = 'boolean' | 'integer' | 'float' | 'string' | 'json'

export interface AlarmSettingsProfileMeta {
  id: number
  name: string
  isActive: boolean
  createdAt: string
  updatedAt: string
}

export interface AlarmSettingEntry {
  key: string
  name: string
  valueType: SystemConfigValueType
  value: unknown
  description: string
}

export interface AlarmSettingsProfileDetail {
  profile: AlarmSettingsProfileMeta
  entries: AlarmSettingEntry[]
}

export interface SystemConfigRow {
  key: string
  name: string
  valueType: SystemConfigValueType
  value: unknown
  description: string
  modifiedById: string | null
  createdAt: string
  updatedAt: string
}
