import { Input } from '@/components/ui/input'

type Props = {
  codeId: number
  label: string
  onLabelChange: (next: string) => void
  newCode: string
  onNewCodeChange: (next: string) => void
  maxUses: string
  onMaxUsesChange: (next: string) => void
  isBusy: boolean
  isSynced?: boolean
}

export function DoorCodeEditBasicsFields({
  codeId,
  label,
  onLabelChange,
  newCode,
  onNewCodeChange,
  maxUses,
  onMaxUsesChange,
  isBusy,
  isSynced = false,
}: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor={`door-code-edit-label-${codeId}`}>
          Label
        </label>
        <Input id={`door-code-edit-label-${codeId}`} value={label} onChange={(e) => onLabelChange(e.target.value)} disabled={isBusy} />
      </div>
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor={`door-code-edit-code-${codeId}`}>
          New code (optional)
        </label>
        <Input
          id={`door-code-edit-code-${codeId}`}
          value={isSynced ? '' : newCode}
          onChange={(e) => onNewCodeChange(e.target.value)}
          placeholder={isSynced ? 'Controlled by lock sync' : '4–8 digits'}
          inputMode="numeric"
          autoComplete="off"
          disabled={isBusy || isSynced}
        />
      </div>
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor={`door-code-edit-max-uses-${codeId}`}>
          Max uses (optional)
        </label>
        <Input
          id={`door-code-edit-max-uses-${codeId}`}
          type="number"
          min={1}
          step={1}
          value={maxUses}
          onChange={(e) => onMaxUsesChange(e.target.value)}
          disabled={isBusy}
        />
      </div>
    </div>
  )
}

