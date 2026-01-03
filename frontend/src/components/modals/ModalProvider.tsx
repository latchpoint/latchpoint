import { ConfirmDeleteModal } from './ConfirmDeleteModal'
import { CodeEntryModal } from './CodeEntryModal'

/**
 * Renders all global modals.
 * Add this once at the app root level.
 */
export function ModalProvider() {
  return (
    <>
      <ConfirmDeleteModal />
      <CodeEntryModal />
      {/* Add other modals here as they're created */}
    </>
  )
}
