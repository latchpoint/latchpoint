import { useState } from 'react'
import { useModal } from '@/stores/modalStore'
import { Modal } from '@/components/ui/modal'
import { Keypad } from '@/components/alarm/Keypad'
import { Alert, AlertDescription } from '@/components/ui/alert'

export function CodeEntryModal() {
  const { isOpen, data, close } = useModal('code-entry')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen || !data) return null

  const handleSubmit = async (code: string) => {
    setIsSubmitting(true)
    setError(null)
    try {
      await data.onSubmit(code)
      close()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invalid code')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = () => {
    setError(null)
    close()
  }

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleCancel()
      }}
      title={data.title}
      description={data.description}
      maxWidthClassName="max-w-sm"
      showCloseButton={false}
    >
      <Keypad
        onSubmit={handleSubmit}
        onCancel={handleCancel}
        disabled={isSubmitting}
        submitLabel={data.submitLabel}
      />
      {error && (
        <Alert variant="error" layout="inline" className="mt-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </Modal>
  )
}
