import { Button } from '@/components/ui/button'

type Props = {
  isBusy: boolean
  isSaving: boolean
  isDeleting: boolean
  onCancel: () => void
  onSave: () => void
  onDelete: () => void
}

export function DoorCodeEditActions({ isBusy, isSaving, isDeleting, onCancel, onSave, onDelete }: Props) {
  return (
    <div className="flex items-center justify-between gap-2">
      <Button variant="destructive" onClick={onDelete} disabled={isBusy}>
        {isDeleting ? 'Deleting…' : 'Delete'}
      </Button>
      <div className="flex items-center gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isBusy}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={isBusy}>
          {isSaving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

