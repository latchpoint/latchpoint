import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { HaTargetEntityIdsPicker } from '@/features/rules/components/then/HaTargetEntityIdsPicker'

type Props = {
  actionId: string
  domain: string
  service: string
  targetEntityIds: string
  serviceDataJson: string
  isSaving: boolean
  entityIdOptions: string[]
  pickerValue: string
  setPickerValue: (next: string) => void
  onChange: (patch: { domain?: string; service?: string; serviceDataJson?: string }) => void
  updateHaActionTargetEntityIds: (actionId: string, nextEntityIds: string[]) => void
}

export function HaCallServiceActionFields({
  actionId,
  domain,
  service,
  targetEntityIds,
  serviceDataJson,
  isSaving,
  entityIdOptions,
  pickerValue,
  setPickerValue,
  onChange,
  updateHaActionTargetEntityIds,
}: Props) {
  return (
    <>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Domain <HelpTip className="ml-1" content="Service domain, e.g. notify, light, switch, siren." />
        </label>
        <Input value={domain} onChange={(e) => onChange({ domain: e.target.value })} placeholder="e.g., notify" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          Service <HelpTip className="ml-1" content="Service name within the domain, e.g. turn_on, turn_off, mobile_app_foo." />
        </label>
        <Input value={service} onChange={(e) => onChange({ service: e.target.value })} placeholder="e.g., mobile_app_phone" />
      </div>

      <HaTargetEntityIdsPicker
        actionId={actionId}
        targetEntityIdsText={targetEntityIds}
        entityIdOptions={entityIdOptions}
        isSaving={isSaving}
        pickerValue={pickerValue}
        setPickerValue={setPickerValue}
        updateHaActionTargetEntityIds={updateHaActionTargetEntityIds}
      />

      <div className="space-y-1 md:col-span-3">
        <label className="text-xs text-muted-foreground">
          Service data (JSON) <HelpTip className="ml-1" content="Optional service_data payload (JSON object)." />
        </label>
        <Textarea
          className="min-h-[96px] font-mono text-xs"
          value={serviceDataJson}
          onChange={(e) => onChange({ serviceDataJson: e.target.value })}
          spellCheck={false}
        />
      </div>
    </>
  )
}

