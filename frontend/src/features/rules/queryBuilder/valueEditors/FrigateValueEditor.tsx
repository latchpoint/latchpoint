/**
 * Custom value editor for frigate_person_detected condition
 * Provides camera/zone selection and threshold configuration
 */
import type { ValueEditorProps } from 'react-querybuilder'
import type { FrigatePersonValue, ValueEditorContext } from '../types'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'

const HELP_TIP_CLASS = 'h-5 w-5 [&_svg]:h-3.5 [&_svg]:w-3.5'

interface FrigateValueEditorProps extends ValueEditorProps {
  context?: ValueEditorContext
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
        <div className="flex items-center gap-1">
          <label className="text-xs font-medium text-muted-foreground">Cameras</label>
          <HelpTip
            className={HELP_TIP_CLASS}
            content="Frigate cameras whose person events should be evaluated. If none are discovered yet, type names comma-separated."
          />
        </div>
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
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Zones (optional)
            </label>
            <HelpTip
              className={HELP_TIP_CLASS}
              content="Only count detections that occurred inside one of these zones. Leave empty to match any zone on the selected cameras."
            />
          </div>
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
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Within (sec)
            </label>
            <HelpTip
              className={HELP_TIP_CLASS}
              content="Backward-looking window. The rule looks for any qualifying person detection in the past N seconds at the moment it evaluates."
            />
          </div>
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
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Min confidence %
            </label>
            <HelpTip
              className={HELP_TIP_CLASS}
              content="Minimum confidence score (0–100) a detection must reach to count as a match."
            />
          </div>
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
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Aggregation
            </label>
            <HelpTip
              className={HELP_TIP_CLASS}
              content="How to collapse multiple detections in the window into one score. Max = highest score; Latest = most recent detection's score; Percentile = the Nth-percentile score across the window."
            />
          </div>
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
            <div className="flex items-center gap-1">
              <label className="text-xs font-medium text-muted-foreground">
                Percentile
              </label>
              <HelpTip
                className={HELP_TIP_CLASS}
                content="Which percentile (1–100) to take when Aggregation is set to Percentile. 90 means 'beat the 90th-percentile detection'."
              />
            </div>
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
        <div className="flex items-center gap-1">
          <label className="text-xs font-medium text-muted-foreground">
            If Frigate unavailable
          </label>
          <HelpTip
            className={HELP_TIP_CLASS}
            content="Fallback when Frigate hasn't reported recent events or is offline. 'Treat as no match' is fail-safe; 'Treat as match' will trigger the rule anyway."
          />
        </div>
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
