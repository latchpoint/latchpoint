import { Button } from '@/components/ui/button'

type Props = {
  editingId: number | null
  isSaving: boolean
  onSubmit: () => void
  onCancel: () => void
  onDelete: () => void
}

export function RuleEditorActions({ editingId, isSaving, onSubmit, onCancel, onDelete }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" onClick={onSubmit} disabled={isSaving}>
        {editingId == null ? 'Create' : 'Save'}
      </Button>
      <Button type="button" variant="outline" onClick={onCancel} disabled={isSaving}>
        Cancel
      </Button>
      {editingId != null ? (
        <Button type="button" variant="destructive" onClick={onDelete} disabled={isSaving}>
          Delete
        </Button>
      ) : null}
    </div>
  )
}

