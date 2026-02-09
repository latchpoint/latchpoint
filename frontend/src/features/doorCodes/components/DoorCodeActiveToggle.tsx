import { Switch } from '@/components/ui/switch'

type Props = {
  id: string
  checked: boolean
  onCheckedChange?: (next: boolean) => void
  disabled: boolean
  hint?: string
}

export function DoorCodeActiveToggle({ id, checked, onCheckedChange, disabled, hint }: Props) {
  return (
    <div className="flex items-center gap-2">
      <Switch checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} aria-labelledby={id} />
      <span id={id} className="text-sm">
        Active
      </span>
      {hint ? <span className="text-xs text-muted-foreground">({hint})</span> : null}
    </div>
  )
}

