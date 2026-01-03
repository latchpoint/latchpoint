import { useState } from 'react'
import { useModal } from '@/stores/modalStore'
import { Modal } from '@/components/ui/modal'
import { Button } from '@/components/ui/button'
import { AlertTriangle } from 'lucide-react'

export function ConfirmDeleteModal() {
  const { isOpen, data, close } = useModal('confirm-delete')
  const [isDeleting, setIsDeleting] = useState(false)

  if (!isOpen || !data) return null

  const handleConfirm = async () => {
    setIsDeleting(true)
    try {
      await data.onConfirm()
      close()
    } catch {
      // Error handled by onConfirm callback
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => !open && close()}
      title={data.title}
      maxWidthClassName="max-w-sm"
    >
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          <div className="rounded-full bg-destructive/10 p-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
          </div>
          <p className="text-sm text-muted-foreground">{data.message}</p>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={close} disabled={isDeleting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={isDeleting}>
            {isDeleting ? 'Deleting...' : 'Delete'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
