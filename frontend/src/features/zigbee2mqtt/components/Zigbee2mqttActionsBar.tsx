import { Button } from '@/components/ui/button'

type Props = {
  isAdmin: boolean
  isBusy: boolean
  canSync: boolean
  onSave: () => void
  onReset: () => void
  onRunSync: () => void
}

export function Zigbee2mqttActionsBar({ isAdmin, isBusy, canSync, onSave, onReset, onRunSync }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button onClick={onSave} disabled={!isAdmin || isBusy}>
        Save
      </Button>
      <Button variant="secondary" onClick={onReset} disabled={!isAdmin || isBusy}>
        Reset
      </Button>
      <Button variant="secondary" onClick={onRunSync} disabled={!isAdmin || isBusy || !canSync}>
        Sync devices
      </Button>
    </div>
  )
}
