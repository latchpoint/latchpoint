/**
 * Generic schema-driven form for integration settings (ADR 0079 Phase 4).
 *
 * Renders form fields from a config_schema definition. Handles:
 * - String, number, integer, boolean field types
 * - Secret fields (password inputs with "A value is saved" / "Clear" UX)
 * - The `enabled` toggle is rendered separately at the top
 */

import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { ConfigSchema, ConfigSchemaProperty } from '@/types/settingsRegistry'
import { Eye, EyeOff, X } from 'lucide-react'
import { useState } from 'react'

type Props = {
  schema: ConfigSchema
  encryptedFields: string[]
  /** Current draft values (camelCase keys, matching the API response shape). */
  values: Record<string, unknown>
  /** Masked boolean flags for secret fields (e.g. hasToken, hasPassword). */
  maskedFlags: Record<string, boolean>
  disabled?: boolean
  onChange: (key: string, value: unknown) => void
}

function SecretField({
  fieldKey,
  property,
  value,
  hasSavedValue,
  disabled,
  onChange,
}: {
  fieldKey: string
  property: ConfigSchemaProperty
  value: string
  hasSavedValue: boolean
  disabled?: boolean
  onChange: (key: string, value: unknown) => void
}) {
  const [editing, setEditing] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  // If there's a saved value and user hasn't started editing, show the "saved" state
  if (hasSavedValue && !editing && !value) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex h-9 flex-1 items-center rounded-md border border-input bg-muted/30 px-3 text-sm text-muted-foreground">
          A value is saved
        </div>
        {!disabled && (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setEditing(true)}
            >
              Change
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                onChange(fieldKey, '')
                setEditing(true)
              }}
              title="Clear saved value"
            >
              <X className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="relative">
      <Input
        type={showPassword ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(fieldKey, e.target.value)}
        disabled={disabled}
        placeholder={property.description}
        className="pr-10"
      />
      <button
        type="button"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onClick={() => setShowPassword(!showPassword)}
        tabIndex={-1}
      >
        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

export function IntegrationSettingsForm({
  schema,
  encryptedFields,
  values,
  maskedFlags,
  disabled,
  onChange,
}: Props) {
  if (!schema.properties) return null

  const properties = Object.entries(schema.properties)

  // Separate `enabled` from other fields — it's rendered as a top-level toggle
  const enabledProp = schema.properties.enabled
  const fieldProperties = properties.filter(([key]) => key !== 'enabled')

  return (
    <div className="space-y-4">
      {enabledProp && (
        <div className="flex items-center justify-between rounded-md border p-3">
          <span className="text-sm font-medium">{enabledProp.title || 'Enabled'}</span>
          <Switch
            checked={Boolean(values.enabled)}
            onCheckedChange={(checked) => onChange('enabled', checked)}
            disabled={disabled}
          />
        </div>
      )}

      <div className="space-y-3">
        {fieldProperties.map(([key, property]) => {
          const isSecret = encryptedFields.includes(key) || property.secret === true
          const maskedKey = `has${key.charAt(0).toUpperCase()}${key.slice(1)}`
          const hasSavedValue = Boolean(maskedFlags[maskedKey])

          if (isSecret) {
            return (
              <FormField
                key={key}
                label={property.title || key}
                htmlFor={`field-${key}`}
                description={property.description}
                size="compact"
              >
                <SecretField
                  fieldKey={key}
                  property={property}
                  value={String(values[key] ?? '')}
                  hasSavedValue={hasSavedValue}
                  disabled={disabled}
                  onChange={onChange}
                />
              </FormField>
            )
          }

          if (property.type === 'boolean') {
            return (
              <FormField
                key={key}
                label={property.title || key}
                description={property.description}
                size="compact"
              >
                <Switch
                  checked={Boolean(values[key])}
                  onCheckedChange={(checked) => onChange(key, checked)}
                  disabled={disabled}
                />
              </FormField>
            )
          }

          if (property.type === 'number' || property.type === 'integer') {
            return (
              <FormField
                key={key}
                label={property.title || key}
                htmlFor={`field-${key}`}
                description={property.description}
                size="compact"
              >
                <Input
                  id={`field-${key}`}
                  type="number"
                  min={property.minimum}
                  max={property.maximum}
                  value={values[key] != null ? String(values[key]) : ''}
                  onChange={(e) => onChange(key, e.target.value === '' ? '' : Number(e.target.value))}
                  disabled={disabled}
                />
              </FormField>
            )
          }

          if (property.type === 'string' && property.enum) {
            return (
              <FormField
                key={key}
                label={property.title || key}
                htmlFor={`field-${key}`}
                description={property.description}
                size="compact"
              >
                <select
                  id={`field-${key}`}
                  value={String(values[key] ?? '')}
                  onChange={(e) => onChange(key, e.target.value)}
                  disabled={disabled}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {property.enum.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </FormField>
            )
          }

          // Default: string input
          return (
            <FormField
              key={key}
              label={property.title || key}
              htmlFor={`field-${key}`}
              description={property.description}
              size="compact"
            >
              <Input
                id={`field-${key}`}
                type="text"
                value={String(values[key] ?? '')}
                onChange={(e) => onChange(key, e.target.value)}
                disabled={disabled}
                placeholder={property.description}
              />
            </FormField>
          )
        })}
      </div>
    </div>
  )
}
