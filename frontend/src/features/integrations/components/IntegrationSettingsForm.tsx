/**
 * Generic schema-driven form for integration settings (ADR 0079 Phase 4).
 *
 * Renders form fields from a config_schema definition. Handles:
 * - String, number, integer, boolean field types
 * - Secret fields (password inputs with "A value is saved" / "Clear" UX)
 *
 * The `enabled` field, if declared in the schema, is intentionally NOT
 * rendered here — consumers own the enabled UI on their overview/header
 * card (e.g. `IntegrationOverviewCard`'s `onEnabledChange`).
 */

import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { ConfigSchema, ConfigSchemaProperty } from '@/types/settingsRegistry'
import { Eye, EyeOff, X } from 'lucide-react'
import { useCallback, useState } from 'react'

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
        aria-label={showPassword ? 'Hide password' : 'Show password'}
      >
        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

function JsonTextareaField({
  fieldKey,
  property,
  value,
  disabled,
  onChange,
}: {
  fieldKey: string
  property: ConfigSchemaProperty
  value: unknown
  disabled?: boolean
  onChange: (key: string, value: unknown) => void
}) {
  const serialize = useCallback(
    (v: unknown) =>
      typeof v === 'object' && v !== null ? JSON.stringify(v, null, 2) : String(v ?? ''),
    [],
  )

  const [rawText, setRawText] = useState(() => serialize(value))
  const [jsonError, setJsonError] = useState<string | null>(null)

  // Sync local text when the canonical value changes externally (e.g. server refetch)
  const serialized = serialize(value)
  const [prevSerialized, setPrevSerialized] = useState(serialized)
  if (serialized !== prevSerialized) {
    setPrevSerialized(serialized)
    setRawText(serialized)
    setJsonError(null)
  }

  return (
    <FormField
      label={property.title || fieldKey}
      htmlFor={`field-${fieldKey}`}
      description={property.description}
      size="compact"
    >
      <textarea
        id={`field-${fieldKey}`}
        value={rawText}
        onChange={(e) => {
          const text = e.target.value
          setRawText(text)
          try {
            const parsed = JSON.parse(text)
            setJsonError(null)
            onChange(fieldKey, parsed)
          } catch {
            setJsonError('Invalid JSON')
          }
        }}
        disabled={disabled}
        rows={3}
        className={`flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 font-mono ${jsonError ? 'border-destructive' : 'border-input'}`}
        placeholder={property.description}
      />
      {jsonError && <p className="text-xs text-destructive mt-1">{jsonError}</p>}
    </FormField>
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

  // Normalize encryptedFields from snake_case to camelCase so they match the
  // camelCased schema property keys produced by the API client's key transform.
  const normalizedEncryptedFields = encryptedFields.map((f) =>
    f.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase())
  )

  const properties = Object.entries(schema.properties)

  // Strip `enabled` — the overview card owns the enable toggle, not this form.
  const fieldProperties = properties.filter(([key]) => key !== 'enabled')

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        {fieldProperties.map(([key, property]) => {
          const isSecret = normalizedEncryptedFields.includes(key) || property.secret === true
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
                  onChange={(e) => {
                    if (e.target.value === '') {
                      // Reset to schema default or minimum instead of persisting empty string
                      const fallback = property.default ?? property.minimum
                      if (fallback != null) {
                        onChange(key, Number(fallback))
                      }
                      return
                    }
                    const parsed = Number(e.target.value)
                    if (!Number.isFinite(parsed)) return
                    let num = property.type === 'integer' ? Math.trunc(parsed) : parsed
                    if (property.minimum != null) num = Math.max(property.minimum, num)
                    if (property.maximum != null) num = Math.min(property.maximum, num)
                    onChange(key, num)
                  }}
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

          // Object / array: JSON textarea
          if (property.type === 'object' || property.type === 'array') {
            return (
              <JsonTextareaField
                key={key}
                fieldKey={key}
                property={property}
                value={values[key]}
                disabled={disabled}
                onChange={onChange}
              />
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
