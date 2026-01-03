import { create } from 'zustand'

export interface Toast {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message?: string
  duration?: number // 0 = persistent (no auto-dismiss)
  dismissible?: boolean
  action?: {
    label: string
    onClick: () => void
  }
}

interface NotificationStore {
  toasts: Toast[]
  addToast: (toast: Omit<Toast, 'id'>) => string
  removeToast: (id: string) => void
  clearToasts: () => void
  clearToastsByType: (type: Toast['type']) => void
}

export const useNotificationStore = create<NotificationStore>((set, get) => ({
  toasts: [],

  addToast: (toast) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
    const newToast: Toast = {
      ...toast,
      id,
      dismissible: toast.dismissible ?? true,
    }

    // Prevent duplicate toasts with same title+message
    const existing = get().toasts.find(
      (t) => t.title === toast.title && t.message === toast.message
    )
    if (existing) {
      return existing.id
    }

    set({ toasts: [...get().toasts, newToast] })

    // Auto-remove after duration (unless 0 = persistent)
    const duration = toast.duration ?? (toast.type === 'error' ? 8000 : 5000)
    if (duration > 0) {
      setTimeout(() => {
        get().removeToast(id)
      }, duration)
    }

    return id
  },

  removeToast: (id) => {
    set({ toasts: get().toasts.filter((t) => t.id !== id) })
  },

  clearToasts: () => {
    set({ toasts: [] })
  },

  clearToastsByType: (type) => {
    set({ toasts: get().toasts.filter((t) => t.type !== type) })
  },
}))

// Convenience function for use outside React
export const toast = {
  info: (title: string, message?: string) =>
    useNotificationStore.getState().addToast({ type: 'info', title, message }),
  success: (title: string, message?: string) =>
    useNotificationStore.getState().addToast({ type: 'success', title, message }),
  warning: (title: string, message?: string) =>
    useNotificationStore.getState().addToast({ type: 'warning', title, message }),
  error: (title: string, message?: string) =>
    useNotificationStore.getState().addToast({ type: 'error', title, message }),
}
