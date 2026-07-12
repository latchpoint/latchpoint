/**
 * Selector-driven form for a Home Assistant service's data fields (ADR-0101).
 *
 * Renders one widget per field whose HA selector type is in the (deliberately
 * small) supported map: number, boolean, select, text, colorRgb. Fields with
 * unknown selectors render nothing here — they stay editable via the Advanced
 * raw-JSON editor, which shares the same `data` object. Widgets own only their mapped
 * keys; everything else in `data` is passed through untouched.
 *
 * Field names arrive camelized by the API client (wire `rgb_color` →
 * `rgbColor`), matching how rule `data` keys appear in-app, so widget keys and
 * data keys line up without re-mapping.
 */
import { useState } from 'react'
import { RgbColorPicker } from 'react-colorful'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { HelpTip } from '@/components/ui/help-tip'
import type { HomeAssistantServiceField } from '@/services/homeAssistant'

export interface ServiceDataFieldsProps {
  fields: Record<string, HomeAssistantServiceField>
  data: Record<string, unknown>
  onChange: (data: Record<string, unknown>) => void
  disabled?: boolean
}

type WidgetKind = 'number' | 'boolean' | 'select' | 'text' | 'colorRgb'

function resolveWidget(selector: Record<string, unknown> | null | undefined): WidgetKind | null {
  if (!selector || typeof selector !== 'object') return null
  if ('number' in selector) return 'number'
  if ('boolean' in selector) return 'boolean'
  if ('select' in selector) return 'select'
  if ('text' in selector) return 'text'
  if ('colorRgb' in selector) return 'colorRgb'
  return null
}

function asRgbTriplet(value: unknown): { r: number; g: number; b: number } | null {
  if (!Array.isArray(value) || value.length !== 3) return null
  const [r, g, b] = value
  if (typeof r !== 'number' || typeof g !== 'number' || typeof b !== 'number') return null
  return { r, g, b }
}

function RgbColorField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string
  value: unknown
  onChange: (value: number[] | undefined) => void
  disabled?: boolean
}) {
  const [isOpen, setIsOpen] = useState(false)
  const rgb = asRgbTriplet(value)

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          disabled={disabled}
          aria-label={`Pick ${label}`}
          aria-expanded={isOpen}
          className="h-8 w-8 shrink-0 rounded-md border border-input"
          style={rgb ? { backgroundColor: `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})` } : undefined}
        />
        <span className="font-mono text-xs text-muted-foreground">
          {rgb ? `[${rgb.r}, ${rgb.g}, ${rgb.b}]` : 'not set'}
        </span>
        {rgb && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange(undefined)
              setIsOpen(false)
            }}
            disabled={disabled}
            className="h-6 px-2 text-xs"
          >
            Clear
          </Button>
        )}
      </div>
      {isOpen && !disabled && (
        <div className="absolute z-50 mt-2 rounded-md border bg-popover p-2 shadow-md">
          <RgbColorPicker
            color={rgb ?? { r: 255, g: 255, b: 255 }}
            onChange={(color) => onChange([color.r, color.g, color.b])}
          />
        </div>
      )}
    </div>
  )
}

interface NumberSelectorConfig {
  min?: number
  max?: number
  step?: number
  unitOfMeasurement?: string
}

function numberConfig(selector: Record<string, unknown>): NumberSelectorConfig {
  const cfg = selector.number
  return cfg && typeof cfg === 'object' ? (cfg as NumberSelectorConfig) : {}
}

function selectOptions(selector: Record<string, unknown>): Array<{ label: string; value: string }> {
  const cfg = selector.select
  const options =
    cfg && typeof cfg === 'object' && Array.isArray((cfg as { options?: unknown[] }).options)
      ? (cfg as { options: unknown[] }).options
      : []
  return options.map((option) => {
    if (option && typeof option === 'object') {
      const { label, value } = option as { label?: unknown; value?: unknown }
      return { label: String(label ?? value ?? ''), value: String(value ?? '') }
    }
    return { label: String(option), value: String(option) }
  })
}

export function ServiceDataFields({ fields, data, onChange, disabled }: ServiceDataFieldsProps) {
  const supported = Object.entries(fields)
    .map(([key, field]) => ({ key, field, widget: resolveWidget(field.selector) }))
    .filter((entry): entry is typeof entry & { widget: WidgetKind } => entry.widget !== null)

  if (supported.length === 0) return null

  const setField = (key: string, value: unknown) => {
    const next = { ...data }
    if (value === undefined || value === '') {
      delete next[key]
    } else {
      next[key] = value
    }
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <label className="text-xs text-muted-foreground">
        Data Fields{' '}
        <HelpTip
          content="Fields this action supports, from Home Assistant. Anything else can be set under Advanced data (JSON)."
          className="ml-1"
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        {supported.map(({ key, field, widget }) => {
          const label = field.name || key
          const selector = field.selector as Record<string, unknown>
          return (
            <div key={key} className="space-y-1">
              <label className="text-xs text-muted-foreground">
                {label}
                {field.required && <span className="text-destructive"> *</span>}
                {field.description && <HelpTip content={field.description} className="ml-1" />}
              </label>
              {widget === 'number' && (() => {
                const cfg = numberConfig(selector)
                const raw = data[key]
                return (
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      value={typeof raw === 'number' ? raw : ''}
                      min={cfg.min}
                      max={cfg.max}
                      step={cfg.step}
                      onChange={(e) =>
                        setField(key, e.target.value === '' ? undefined : Number(e.target.value))
                      }
                      disabled={disabled}
                      aria-label={label}
                    />
                    {cfg.unitOfMeasurement && (
                      <span className="text-xs text-muted-foreground">{cfg.unitOfMeasurement}</span>
                    )}
                  </div>
                )
              })()}
              {widget === 'boolean' && (
                <div>
                  <Switch
                    checked={Boolean(data[key])}
                    onCheckedChange={(checked) => setField(key, checked)}
                    disabled={disabled}
                    aria-label={label}
                  />
                </div>
              )}
              {widget === 'select' && (
                <Select
                  size="sm"
                  value={data[key] === undefined ? '' : String(data[key])}
                  onChange={(e) => setField(key, e.target.value === '' ? undefined : e.target.value)}
                  disabled={disabled}
                  aria-label={label}
                >
                  <option value="">(not set)</option>
                  {selectOptions(selector).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              )}
              {widget === 'text' && (
                <Input
                  value={typeof data[key] === 'string' ? (data[key] as string) : ''}
                  onChange={(e) => setField(key, e.target.value === '' ? undefined : e.target.value)}
                  disabled={disabled}
                  aria-label={label}
                />
              )}
              {widget === 'colorRgb' && (
                <RgbColorField
                  label={label}
                  value={data[key]}
                  onChange={(value) => setField(key, value)}
                  disabled={disabled}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
