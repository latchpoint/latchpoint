/**
 * Types for the settings registry API (ADR 0079).
 * The registry exposes config_schema and encrypted_fields so the frontend
 * can render schema-driven forms for integration settings.
 */

export interface ConfigSchemaProperty {
  type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'
  title?: string
  description?: string
  secret?: boolean
  format?: string
  minimum?: number
  maximum?: number
  enum?: string[]
  default?: unknown
  items?: { type: string }
  additionalProperties?: Record<string, unknown>
}

export interface ConfigSchema {
  type: 'object'
  properties: Record<string, ConfigSchemaProperty>
  required?: string[]
}

export interface SettingsRegistryEntry {
  key: string
  name: string
  description: string
  configSchema: ConfigSchema
  encryptedFields: string[]
}
