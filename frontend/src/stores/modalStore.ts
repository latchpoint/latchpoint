import { create } from 'zustand'
import type { Sensor, AlarmCode, Rule } from '@/types'

/**
 * Registry of all modal types and their required data.
 * Add new modals here to get type safety throughout the app.
 */
export interface ModalRegistry {
  // Confirmation modals
  'confirm-delete': {
    title: string
    message: string
    itemType: 'code' | 'rule' | 'sensor' | 'user'
    itemId: string | number
    onConfirm: () => void | Promise<void>
  }
  'confirm-action': {
    title: string
    message: string
    confirmLabel?: string
    variant?: 'default' | 'destructive'
    onConfirm: () => void | Promise<void>
  }

  // Code modals
  'code-entry': {
    title: string
    description?: string
    submitLabel?: string
    onSubmit: (code: string) => void | Promise<void>
  }

  // Alarm modals
  'bypass-sensors': {
    sensors: Sensor[]
    onConfirm: (bypassedIds: string[]) => void
  }

  // Entity modals
  'sensor-details': {
    sensor: Sensor
  }
  'rule-details': {
    rule: Rule
  }
  'code-edit': {
    code: AlarmCode
    onSave: () => void
  }
}

type ModalName = keyof ModalRegistry

interface ModalState<K extends ModalName = ModalName> {
  name: K
  data: ModalRegistry[K]
}

interface ModalStore {
  /** Currently open modal, or null if none */
  modal: ModalState | null

  /** Open a modal with type-safe data */
  openModal: <K extends ModalName>(name: K, data: ModalRegistry[K]) => void

  /** Close the current modal */
  closeModal: () => void

  /** Check if a specific modal is open */
  isOpen: <K extends ModalName>(name: K) => boolean
}

export const useModalStore = create<ModalStore>((set, get) => ({
  modal: null,

  openModal: (name, data) => {
    set({ modal: { name, data } as ModalState })
  },

  closeModal: () => {
    set({ modal: null })
  },

  isOpen: (name) => {
    return get().modal?.name === name
  },
}))

/**
 * Hook for working with a specific modal type.
 * Returns type-safe data and controls.
 */
export function useModal<K extends ModalName>(name: K) {
  const modal = useModalStore((s) => s.modal)
  const openModal = useModalStore((s) => s.openModal)
  const closeModal = useModalStore((s) => s.closeModal)

  const isOpen = modal?.name === name
  const data = isOpen ? (modal.data as ModalRegistry[K]) : null

  return {
    isOpen,
    data,
    open: (data: ModalRegistry[K]) => openModal(name, data),
    close: closeModal,
  }
}
