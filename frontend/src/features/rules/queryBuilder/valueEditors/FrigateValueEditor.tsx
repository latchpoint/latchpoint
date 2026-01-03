/**
 * Custom value editor for frigate_person_detected condition
 * Provides camera/zone selection and threshold configuration
 */
import type { ValueEditorProps } from 'react-querybuilder'
import type { FrigatePersonValue } from '../types'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'

interface FrigateContext {
  cameras?: string[]
  zonesByCamera?: Record<string, string[]>
}

interface FrigateValueEditorProps extends ValueEditorProps {
  context?: {
    frigate?: FrigateContext
  }
}

export function FrigateValueEditor({
  value,
  handleOnChange,
  disabled,
  context,
}: FrigateValueEditorProps) {
  const currentValue = (value as FrigatePersonValue) || {
    cameras: [],
    zones: [],
    withinSeconds: 10,
    minConfidencePct: 85,
    aggregation: 'max',
    onUnavailable: 'treat_as_no_match',
  }

  const availableCameras = context?.frigate?.cameras || []
  const zonesByCamera = context?.frigate?.zonesByCamera || {}

  // Get all zones for selected cameras
  const availableZones = Array.from(
    new Set(currentValue.cameras.flatMap((cam) => zonesByCamera[cam] || []))
  )

  const updateValue = (updates: Partial<FrigatePersonValue>) => {
    handleOnChange({ ...currentValue, ...updates } as FrigatePersonValue)
  }

  const toggleCamera = (camera: string) => {
    const newCameras = currentValue.cameras.includes(camera)
      ? currentValue.cameras.filter((c) => c !== camera)
      : [...currentValue.cameras, camera]
    updateValue({ cameras: newCameras })
  }

  const toggleZone = (zone: string) => {
    const newZones = currentValue.zones.includes(zone)
      ? currentValue.zones.filter((z) => z !== zone)
      : [...currentValue.zones, zone]
    updateValue({ zones: newZones })
  }

  return (
    <div className="space-y-3 rounded-md border bg-muted/30 p-3">
      {/* Cameras */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Cameras</label>
        <div className="flex flex-wrap gap-1.5">
          {availableCameras.length === 0 ? (
            <Input
              type="text"
              placeholder="Enter camera names (comma-separated)"
              value={currentValue.cameras.join(', ')}
              onChange={(e) =>
                updateValue({
                  cameras: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              disabled={disabled}
              className="h-8"
            />
          ) : (
            availableCameras.map((camera) => (
              <button
                key={camera}
                type="button"
                disabled={disabled}
                onClick={() => toggleCamera(camera)}
                className={cn(
                  'rounded-md px-2 py-1 text-xs font-medium transition-colors border',
                  currentValue.cameras.includes(camera)
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-input bg-background hover:bg-accent'
                )}
              >
                {camera}
              </button>
            ))
          )}
        </div>
      </div>

      {/* Zones (optional) */}
      {availableZones.length > 0 && (
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Zones (optional)
          </label>
          <div className="flex flex-wrap gap-1.5">
            {availableZones.map((zone) => (
              <button
                key={zone}
                type="button"
                disabled={disabled}
                onClick={() => toggleZone(zone)}
                className={cn(
                  'rounded-md px-2 py-1 text-xs font-medium transition-colors border',
                  currentValue.zones.includes(zone)
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-input bg-background hover:bg-accent'
                )}
              >
                {zone}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Thresholds row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Within (sec)
          </label>
          <Input
            type="number"
            min={1}
            max={3600}
            value={currentValue.withinSeconds}
            onChange={(e) =>
              updateValue({ withinSeconds: parseInt(e.target.value) || 10 })
            }
            disabled={disabled}
            className="h-8"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Min confidence %
          </label>
          <Input
            type="number"
            min={0}
            max={100}
            value={currentValue.minConfidencePct}
            onChange={(e) =>
              updateValue({ minConfidencePct: parseFloat(e.target.value) || 85 })
            }
            disabled={disabled}
            className="h-8"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Aggregation
          </label>
          <Select
            value={currentValue.aggregation}
            onChange={(e) =>
              updateValue({
                aggregation: e.target.value as 'max' | 'latest' | 'percentile',
              })
            }
            disabled={disabled}
            size="sm"
          >
            <option value="max">Max</option>
            <option value="latest">Latest</option>
            <option value="percentile">Percentile</option>
          </Select>
        </div>

        {currentValue.aggregation === 'percentile' && (
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Percentile
            </label>
            <Input
              type="number"
              min={1}
              max={100}
              value={currentValue.percentile || 90}
              onChange={(e) =>
                updateValue({ percentile: parseInt(e.target.value) || 90 })
              }
              disabled={disabled}
              className="h-8"
            />
          </div>
        )}
      </div>

      {/* On unavailable */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          If Frigate unavailable
        </label>
        <Select
          value={currentValue.onUnavailable}
          onChange={(e) =>
            updateValue({
              onUnavailable: e.target.value as 'treat_as_match' | 'treat_as_no_match',
            })
          }
          disabled={disabled}
          size="sm"
        >
          <option value="treat_as_no_match">Treat as no match (safe)</option>
          <option value="treat_as_match">Treat as match (trigger anyway)</option>
        </Select>
      </div>
    </div>
  )
}
