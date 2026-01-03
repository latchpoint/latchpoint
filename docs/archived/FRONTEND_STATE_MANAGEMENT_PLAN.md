# Frontend State Management Improvement Plan

> Archived: implemented; kept for historical context.

## Current State Analysis

### Existing Store Structure

**`src/stores/uiStore.ts`** - Single monolithic store handling:
- Sidebar state (open, collapsed)
- Theme (light/dark/system)
- Modals (activeModal: string, modalData: unknown)
- Toasts (array of toast objects)
- Mobile detection (isMobile)

**`src/stores/notificationStore.ts`** - Already created in error handling phase:
- Enhanced toast system with duplicate prevention
- Type-safe toast API

### Current Usage Patterns

| Component | Store Fields Used |
|-----------|-------------------|
| `App.tsx` | Calls `useUIStore()` to initialize |
| `UIBootstrap.tsx` | `setIsMobile`, `theme` |
| `Header.tsx` | `toggleSidebar`, `theme`, `setTheme`, `isMobile` |
| `Sidebar.tsx` | `sidebarOpen`, `sidebarCollapsed`, `setSidebarCollapsed` |

### Issues Identified

1. **Monolithic store** - Unrelated concerns bundled together
2. **Unused modal system** - `activeModal`/`modalData` defined but not used
3. **Modal data is `unknown`** - No type safety for modal payloads
4. **Theme sync in store action** - Side effect in `setTheme` action
5. **Duplicate toast code** - `uiStore` has toasts, but we now have `notificationStore`
6. **Local state explosion** - Pages like `CodesPage` have 25+ `useState` calls for edit forms

---

## Implementation Plan

### Phase 1: Split Stores by Domain

Split `uiStore` into focused, single-responsibility stores.

#### 1.1 Create Layout Store

**File:** `src/stores/layoutStore.ts`

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface LayoutStore {
  // Sidebar
  sidebarOpen: boolean
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  setSidebarCollapsed: (collapsed: boolean) => void

  // Mobile
  isMobile: boolean
  setIsMobile: (isMobile: boolean) => void
}

export const useLayoutStore = create<LayoutStore>()(
  persist(
    (set, get) => ({
      // Sidebar
      sidebarOpen: true,
      sidebarCollapsed: false,
      toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      // Mobile
      isMobile: false,
      setIsMobile: (isMobile) => set({ isMobile }),
    }),
    {
      name: 'alarm-layout',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
)
```

#### 1.2 Create Theme Store

**File:** `src/stores/themeStore.ts`

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark' | 'system'

interface ThemeStore {
  theme: Theme
  setTheme: (theme: Theme) => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      theme: 'system',
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: 'alarm-theme',
    }
  )
)
```

#### 1.3 Update Theme Provider

Move DOM theme sync out of store action into a React effect.

**File:** `src/components/providers/ThemeProvider.tsx`

```typescript
import { useEffect } from 'react'
import { useThemeStore } from '@/stores/themeStore'

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('light', 'dark')

    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

      const applySystemTheme = () => {
        root.classList.remove('light', 'dark')
        root.classList.add(mediaQuery.matches ? 'dark' : 'light')
      }

      applySystemTheme()
      mediaQuery.addEventListener('change', applySystemTheme)
      return () => mediaQuery.removeEventListener('change', applySystemTheme)
    } else {
      root.classList.add(theme)
    }
  }, [theme])

  return <>{children}</>
}
```

---

### Phase 2: Typed Modal System

Create a type-safe modal registry that prevents runtime errors.

#### 2.1 Define Modal Registry

**File:** `src/stores/modalStore.ts`

```typescript
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
```

#### 2.2 Create Modal Components

**File:** `src/components/modals/ConfirmDeleteModal.tsx`

```typescript
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
      // Error handled by onConfirm
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
```

**File:** `src/components/modals/CodeEntryModal.tsx`

```typescript
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

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => !open && close()}
      title={data.title}
      description={data.description}
      maxWidthClassName="max-w-sm"
      showCloseButton={false}
    >
      <Keypad
        onSubmit={handleSubmit}
        onCancel={close}
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
```

#### 2.3 Create Modal Provider

**File:** `src/components/providers/ModalProvider.tsx`

```typescript
import { ConfirmDeleteModal } from '@/components/modals/ConfirmDeleteModal'
import { CodeEntryModal } from '@/components/modals/CodeEntryModal'
// Import other modals as they're created

/**
 * Renders all global modals.
 * Add this once at the app root level.
 */
export function ModalProvider() {
  return (
    <>
      <ConfirmDeleteModal />
      <CodeEntryModal />
      {/* Add other modals here */}
    </>
  )
}
```

---

### Phase 3: Update Components

#### 3.1 Update UIBootstrap

Replace UIBootstrap with separate providers.

**File:** `src/components/providers/LayoutBootstrap.tsx`

```typescript
import { useEffect } from 'react'
import { useLayoutStore } from '@/stores/layoutStore'

export function LayoutBootstrap() {
  const setIsMobile = useLayoutStore((s) => s.setIsMobile)

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 1024)
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [setIsMobile])

  return null
}
```

#### 3.2 Update Header

```typescript
// Before
import { useUIStore } from '@/stores'
const { toggleSidebar, theme, setTheme, isMobile } = useUIStore()

// After
import { useLayoutStore } from '@/stores/layoutStore'
import { useThemeStore } from '@/stores/themeStore'

const { toggleSidebar, isMobile } = useLayoutStore()
const { theme, setTheme } = useThemeStore()
```

#### 3.3 Update Sidebar

```typescript
// Before
import { useUIStore } from '@/stores'
const { sidebarOpen, sidebarCollapsed, setSidebarCollapsed } = useUIStore()

// After
import { useLayoutStore } from '@/stores/layoutStore'
const { sidebarOpen, sidebarCollapsed, setSidebarCollapsed } = useLayoutStore()
```

#### 3.4 Update App.tsx

```typescript
// Before
import { useUIStore } from '@/stores'
// ...
function AppContent() {
  useUIStore()
  // ...
}

// After
import { ThemeProvider } from '@/components/providers/ThemeProvider'
import { LayoutBootstrap } from '@/components/providers/LayoutBootstrap'
import { ModalProvider } from '@/components/providers/ModalProvider'

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
          <AppErrorBoundary>
            <LayoutBootstrap />
            <AppContent />
            <ModalProvider />
          </AppErrorBoundary>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

---

### Phase 4: Remove Legacy Store Code

#### 4.1 Update Store Exports

**File:** `src/stores/index.ts`

```typescript
// Layout
export { useLayoutStore } from './layoutStore'

// Theme
export { useThemeStore } from './themeStore'

// Modals
export { useModalStore, useModal } from './modalStore'

// Notifications (already created)
export { useNotificationStore, toast } from './notificationStore'

// Legacy - deprecate
/** @deprecated Use useLayoutStore, useThemeStore instead */
export { useUIStore, default as uiStore } from './uiStore'
```

#### 4.2 Remove Toast Duplicate from uiStore

After confirming all toast usage migrated to `notificationStore`, remove toast-related code from `uiStore`.

---

### Phase 5: Usage Examples

#### Opening a Confirm Delete Modal

```typescript
import { useModalStore } from '@/stores/modalStore'

function RuleRow({ rule }: { rule: Rule }) {
  const openModal = useModalStore((s) => s.openModal)
  const deleteRule = useDeleteRuleMutation()

  const handleDelete = () => {
    openModal('confirm-delete', {
      title: 'Delete Rule',
      message: `Are you sure you want to delete "${rule.name}"? This action cannot be undone.`,
      itemType: 'rule',
      itemId: rule.id,
      onConfirm: async () => {
        await deleteRule.mutateAsync(rule.id)
      },
    })
  }

  return (
    <Button variant="destructive" onClick={handleDelete}>
      Delete
    </Button>
  )
}
```

#### Opening Code Entry Modal

```typescript
import { useModal } from '@/stores/modalStore'

function ArmButton({ targetState }: { targetState: AlarmStateType }) {
  const { open: openCodeEntry } = useModal('code-entry')
  const { arm } = useAlarm()

  const handleArm = () => {
    openCodeEntry({
      title: 'Enter Code to Arm',
      description: `Arming to ${targetState}`,
      submitLabel: 'Arm',
      onSubmit: async (code) => {
        await arm(targetState, code)
      },
    })
  }

  return <Button onClick={handleArm}>Arm</Button>
}
```

---

## File Structure Summary

```
src/stores/
├── index.ts              # Barrel exports
├── layoutStore.ts        # NEW: Sidebar + mobile
├── themeStore.ts         # NEW: Theme only
├── modalStore.ts         # NEW: Typed modal registry
├── notificationStore.ts  # Already exists (from error handling)
└── uiStore.ts            # DEPRECATED: Keep for migration

src/components/providers/
├── ThemeProvider.tsx     # NEW: Theme DOM sync
├── LayoutBootstrap.tsx   # NEW: Mobile detection
├── ModalProvider.tsx     # NEW: Renders all modals
├── ...

src/components/modals/
├── ConfirmDeleteModal.tsx    # NEW
├── CodeEntryModal.tsx        # NEW
├── ConfirmActionModal.tsx    # NEW
├── BypassSensorsModal.tsx    # NEW (future)
└── index.ts
```

---

## Implementation Order

### Step 1: Create New Stores (No Breaking Changes)
1. Create `layoutStore.ts`
2. Create `themeStore.ts`
3. Create `modalStore.ts`

### Step 2: Create Providers
4. Create `ThemeProvider.tsx`
5. Create `LayoutBootstrap.tsx`
6. Create modal components (`ConfirmDeleteModal.tsx`, `CodeEntryModal.tsx`)
7. Create `ModalProvider.tsx`

### Step 3: Migrate Components
8. Update `App.tsx` to use new providers
9. Update `Header.tsx` to use split stores
10. Update `Sidebar.tsx` to use split stores
11. Remove `UIBootstrap.tsx` (replaced by new providers)

### Step 4: Cleanup
12. Remove toast code from `uiStore`
13. Remove modal code from `uiStore`
14. Deprecate remaining `uiStore` code
15. Update store exports

---

## Testing Checklist

After implementation, verify:

- [ ] Theme persists across page reloads
- [ ] Theme responds to system preference changes when set to "system"
- [ ] Sidebar collapsed state persists
- [ ] Mobile detection works on resize
- [ ] Confirm delete modal opens with correct data
- [ ] Code entry modal submits and closes on success
- [ ] Code entry modal shows error on failure
- [ ] Modal closes on backdrop click
- [ ] Modal closes on Escape key
- [ ] Multiple modals can't open simultaneously
- [ ] Toast notifications still work
- [ ] No TypeScript errors
- [ ] Build succeeds

---

## Migration Notes

### For Existing Code

Replace:
```typescript
// Old
import { useUIStore } from '@/stores'
const { theme, setTheme, sidebarOpen, addToast } = useUIStore()

// New
import { useThemeStore, useLayoutStore, useNotificationStore } from '@/stores'
const { theme, setTheme } = useThemeStore()
const { sidebarOpen } = useLayoutStore()
const { addToast } = useNotificationStore()
```

### For New Modal Usage

Replace local modal state:
```typescript
// Old - local state
const [showDeleteModal, setShowDeleteModal] = useState(false)
const [deleteItem, setDeleteItem] = useState<Item | null>(null)

// New - global typed modal
const { open: openDelete } = useModal('confirm-delete')
openDelete({ title: '...', message: '...', onConfirm: handleDelete })
```
