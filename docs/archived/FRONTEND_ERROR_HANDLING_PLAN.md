# Frontend Error Handling Improvement Plan

> Archived: implemented; kept for historical context.

## Current State Analysis

### What Exists

1. **Global Error Boundary** (`src/components/providers/AppErrorBoundary.tsx`)
   - Catches unhandled render errors
   - Shows error message with "Try again" and "Reload page" buttons
   - Logs to console in development

2. **API Error Handling** (`src/services/api.ts`)
   - Parses error responses into `ApiError` type
   - Extracts message from `detail`, `message`, `non_field_errors`, or field errors
   - Throws error for components to catch

3. **Component-Level Error Display** (e.g., `AlarmPanel.tsx`)
   - Uses `error` from hooks, displays in `Alert` component
   - Manual try/catch in async handlers with empty catch blocks

4. **WebSocket Error Handling** (`src/services/websocket.ts`)
   - Sets status to 'error' on WebSocket errors
   - Logs parse errors to console
   - Exponential backoff reconnection

5. **Toast System** (`src/stores/uiStore.ts`)
   - `addToast()` for notifications
   - Types: info, success, warning, error
   - Auto-dismiss after duration

### Current Gaps

| Gap | Impact |
|-----|--------|
| Single global error boundary | One component crash breaks entire app |
| Empty catch blocks | Errors silently swallowed |
| No error categorization | All errors treated the same |
| No 401/403 handling | Users see generic errors instead of being redirected |
| No connection status UI | Users don't know when they're offline |
| Inconsistent error display | Some errors in Alert, some in toast, some logged |
| No error recovery strategies | Only options are "try again" or reload |
| Query errors not centralized | Each component handles errors differently |

---

## Implementation Plan

### Phase 1: Error Type System

**Goal:** Create a structured way to categorize and handle different error types.

#### 1.1 Create Error Types

**File:** `src/lib/errors.ts`

```typescript
/**
 * Error categories for different handling strategies
 */
export type ErrorCategory =
  | 'auth'        // 401/403 - redirect to login
  | 'validation'  // 400/422 - show field errors
  | 'not_found'   // 404 - show not found message
  | 'network'     // Network failures - show connection error
  | 'server'      // 500+ - show server error
  | 'timeout'     // Request timeout
  | 'unknown'     // Fallback

/**
 * Structured error with category and metadata
 */
export interface AppError {
  category: ErrorCategory
  message: string
  code?: string
  details?: Record<string, string[]>
  originalError?: unknown
  timestamp: number
  recoverable: boolean
}

/**
 * Type guard for API errors
 */
export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    typeof (error as Record<string, unknown>).message === 'string'
  )
}

/**
 * Type guard for network errors
 */
export function isNetworkError(error: unknown): boolean {
  if (error instanceof TypeError) {
    return error.message.includes('fetch') || error.message.includes('network')
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false // Intentional abort, not a network error
  }
  return false
}

/**
 * Type guard for timeout errors
 */
export function isTimeoutError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/**
 * Categorize any error into an AppError
 */
export function categorizeError(error: unknown): AppError {
  const timestamp = Date.now()

  // Network errors
  if (isNetworkError(error)) {
    return {
      category: 'network',
      message: 'Unable to connect to the server. Check your connection.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Timeout errors
  if (isTimeoutError(error)) {
    return {
      category: 'timeout',
      message: 'Request timed out. Please try again.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // API errors with status codes
  if (isApiError(error)) {
    const code = parseInt(error.code || '0', 10)

    if (code === 401 || code === 403) {
      return {
        category: 'auth',
        message: code === 401 ? 'Session expired. Please log in again.' : 'You do not have permission to perform this action.',
        code: error.code,
        recoverable: false,
        timestamp,
        originalError: error,
      }
    }

    if (code === 404) {
      return {
        category: 'not_found',
        message: error.message || 'The requested resource was not found.',
        code: error.code,
        recoverable: false,
        timestamp,
        originalError: error,
      }
    }

    if (code === 400 || code === 422) {
      return {
        category: 'validation',
        message: error.message || 'Please check your input and try again.',
        code: error.code,
        details: error.details,
        recoverable: true,
        timestamp,
        originalError: error,
      }
    }

    if (code >= 500) {
      return {
        category: 'server',
        message: 'The server encountered an error. Please try again later.',
        code: error.code,
        recoverable: true,
        timestamp,
        originalError: error,
      }
    }

    // API error without recognizable code
    return {
      category: 'unknown',
      message: error.message || 'An unexpected error occurred.',
      code: error.code,
      details: error.details,
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Standard Error objects
  if (error instanceof Error) {
    return {
      category: 'unknown',
      message: error.message || 'An unexpected error occurred.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Unknown error type
  return {
    category: 'unknown',
    message: 'An unexpected error occurred.',
    recoverable: true,
    timestamp,
    originalError: error,
  }
}

/**
 * Get user-friendly error message
 */
export function getErrorMessage(error: unknown): string {
  const appError = categorizeError(error)
  return appError.message
}
```

#### 1.2 Update ApiError Type

**File:** `src/types/api.ts` (modify existing)

```typescript
export interface ApiError {
  message: string
  code: string  // Make required, default to status code string
  details?: Record<string, string[]>
}
```

---

### Phase 2: Centralized Error Handler

**Goal:** Single place to handle errors with consistent behavior per category.

#### 2.1 Create Error Handler

**File:** `src/lib/errorHandler.ts`

```typescript
import { categorizeError, type AppError, type ErrorCategory } from './errors'
import { useNotificationStore } from '@/stores/notificationStore'

type ErrorHandlerOptions = {
  silent?: boolean           // Don't show toast
  showDetails?: boolean      // Show field-level details
  onAuth?: () => void        // Custom auth error handler
  onRetry?: () => void       // Retry callback for recoverable errors
}

/**
 * Central error handler that routes errors to appropriate UI feedback
 */
export function handleError(error: unknown, options: ErrorHandlerOptions = {}): AppError {
  const appError = categorizeError(error)
  const { addToast } = useNotificationStore.getState()

  // Log all errors in development
  if (import.meta.env.DEV) {
    console.error(`[${appError.category}]`, appError.message, appError.originalError)
  }

  // Handle by category
  switch (appError.category) {
    case 'auth':
      handleAuthError(appError, options)
      break

    case 'validation':
      handleValidationError(appError, options)
      break

    case 'network':
      handleNetworkError(appError, options)
      break

    case 'server':
      handleServerError(appError, options)
      break

    case 'timeout':
      handleTimeoutError(appError, options)
      break

    case 'not_found':
      handleNotFoundError(appError, options)
      break

    default:
      handleUnknownError(appError, options)
  }

  return appError
}

function handleAuthError(error: AppError, options: ErrorHandlerOptions) {
  if (options.onAuth) {
    options.onAuth()
    return
  }

  // Store current path for redirect after login
  const currentPath = window.location.pathname + window.location.search
  if (currentPath !== '/login') {
    sessionStorage.setItem('redirectAfterLogin', currentPath)
  }

  // Redirect to login
  window.location.href = '/login?reason=session_expired'
}

function handleValidationError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  // If we have field details and showDetails is true, format them
  if (error.details && options.showDetails) {
    const detailMessages = Object.entries(error.details)
      .map(([field, messages]) => `${field}: ${messages.join(', ')}`)
      .join('\n')

    addToast({
      type: 'warning',
      title: 'Validation Error',
      message: detailMessages || error.message,
    })
  } else {
    addToast({
      type: 'warning',
      title: 'Validation Error',
      message: error.message,
    })
  }
}

function handleNetworkError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Connection Error',
    message: error.message,
    duration: 0, // Don't auto-dismiss network errors
  })
}

function handleServerError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Server Error',
    message: error.message,
  })
}

function handleTimeoutError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'warning',
    title: 'Request Timeout',
    message: error.message,
  })
}

function handleNotFoundError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'warning',
    title: 'Not Found',
    message: error.message,
  })
}

function handleUnknownError(error: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Error',
    message: error.message,
  })
}

/**
 * Create a wrapped async function that automatically handles errors
 */
export function withErrorHandling<T extends (...args: unknown[]) => Promise<unknown>>(
  fn: T,
  options: ErrorHandlerOptions = {}
): T {
  return (async (...args: Parameters<T>) => {
    try {
      return await fn(...args)
    } catch (error) {
      handleError(error, options)
      throw error // Re-throw for component-level handling if needed
    }
  }) as T
}
```

---

### Phase 3: Feature-Level Error Boundaries

**Goal:** Isolate errors so one component crashing doesn't break the entire app.

#### 3.1 Create Feature Error Boundary

**File:** `src/components/providers/FeatureErrorBoundary.tsx`

```typescript
import { Component, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  /** Name of the feature for error messages */
  feature: string
  /** Custom fallback UI */
  fallback?: ReactNode
  /** Called when user clicks retry */
  onRetry?: () => void
  /** Called when error occurs (for parent notification) */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
  /** Render inline (small) or as card (larger) */
  variant?: 'inline' | 'card'
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: React.ErrorInfo | null
}

export class FeatureErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, errorInfo: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    this.setState({ errorInfo })

    // Log error with feature context
    console.error(`[FeatureError:${this.props.feature}]`, {
      error: error.message,
      stack: error.stack,
      componentStack: errorInfo.componentStack,
    })

    // Notify parent if callback provided
    this.props.onError?.(error, errorInfo)
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
    this.props.onRetry?.()
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    // Custom fallback
    if (this.props.fallback) {
      return this.props.fallback
    }

    const { variant = 'card' } = this.props

    // Inline variant - minimal UI
    if (variant === 'inline') {
      return (
        <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">Failed to load {this.props.feature}</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2"
            onClick={this.handleRetry}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      )
    }

    // Card variant - more prominent
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-6">
        <div className="flex flex-col items-center text-center">
          <div className="rounded-full bg-destructive/10 p-3">
            <AlertTriangle className="h-6 w-6 text-destructive" />
          </div>
          <h3 className="mt-4 font-semibold">Failed to load {this.props.feature}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Something went wrong while rendering this section.
          </p>

          {/* Show error details in development */}
          {import.meta.env.DEV && this.state.error && (
            <pre className="mt-4 max-h-32 w-full overflow-auto rounded-md bg-muted p-2 text-left text-xs">
              {this.state.error.message}
            </pre>
          )}

          <div className="mt-4 flex gap-2">
            <Button size="sm" onClick={this.handleRetry}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Try Again
            </Button>
          </div>
        </div>
      </div>
    )
  }
}
```

#### 3.2 Create Hook for Programmatic Error Boundary Reset

**File:** `src/hooks/useErrorBoundary.ts`

```typescript
import { useCallback, useState } from 'react'

/**
 * Hook to programmatically trigger error boundary reset
 */
export function useErrorBoundaryReset() {
  const [resetKey, setResetKey] = useState(0)

  const reset = useCallback(() => {
    setResetKey((k) => k + 1)
  }, [])

  return { resetKey, reset }
}
```

**Usage Example:**

```tsx
function DashboardPage() {
  const { resetKey, reset } = useErrorBoundaryReset()
  const { refresh } = useAlarm()

  const handleRetry = () => {
    refresh()
    reset()
  }

  return (
    <div>
      <FeatureErrorBoundary
        key={resetKey}
        feature="Alarm Panel"
        onRetry={handleRetry}
      >
        <AlarmPanel />
      </FeatureErrorBoundary>

      <FeatureErrorBoundary
        key={resetKey}
        feature="Sensor List"
        variant="inline"
      >
        <SensorList />
      </FeatureErrorBoundary>
    </div>
  )
}
```

---

### Phase 4: Connection Status Component

**Goal:** Show users when they're disconnected with reconnection options.

#### 4.1 Create Connection Status Banner

**File:** `src/components/ui/ConnectionStatusBanner.tsx`

```typescript
import { useEffect, useState } from 'react'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'
import { wsManager } from '@/services/websocket'
import { WifiOff, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react'
import { Button } from './button'
import { cn } from '@/lib/utils'

export function ConnectionStatusBanner() {
  const { data: wsStatus } = useWebSocketStatus()
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const [isReconnecting, setIsReconnecting] = useState(false)
  const [showSuccess, setShowSuccess] = useState(false)

  // Track browser online/offline status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Show success briefly when reconnected
  useEffect(() => {
    if (wsStatus === 'connected' && isReconnecting) {
      setIsReconnecting(false)
      setShowSuccess(true)
      const timer = setTimeout(() => setShowSuccess(false), 2000)
      return () => clearTimeout(timer)
    }
  }, [wsStatus, isReconnecting])

  const handleReconnect = () => {
    setIsReconnecting(true)
    wsManager.connect()
  }

  // Determine what to show
  const showOffline = !isOnline
  const showDisconnected = isOnline && wsStatus === 'disconnected'
  const showConnecting = wsStatus === 'connecting' || isReconnecting
  const showError = wsStatus === 'error'

  // Don't render if everything is fine
  if (!showOffline && !showDisconnected && !showConnecting && !showError && !showSuccess) {
    return null
  }

  return (
    <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2">
      {/* Success message */}
      {showSuccess && (
        <div className="flex items-center gap-2 rounded-full bg-green-600 px-4 py-2 text-white shadow-lg animate-in fade-in slide-in-from-bottom-2">
          <CheckCircle className="h-4 w-4" />
          <span className="text-sm font-medium">Connected</span>
        </div>
      )}

      {/* Offline - browser has no network */}
      {showOffline && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <WifiOff className="h-4 w-4" />
          <span className="text-sm font-medium">No internet connection</span>
        </div>
      )}

      {/* Connecting */}
      {!showOffline && showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-yellow-600 px-4 py-2 text-white shadow-lg">
          <RefreshCw className="h-4 w-4 animate-spin" />
          <span className="text-sm font-medium">Reconnecting...</span>
        </div>
      )}

      {/* Disconnected - can try to reconnect */}
      {!showOffline && showDisconnected && !showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <WifiOff className="h-4 w-4" />
          <span className="text-sm font-medium">Disconnected</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-destructive-foreground hover:bg-white/20"
            onClick={handleReconnect}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Error state */}
      {!showOffline && showError && !showConnecting && (
        <div className="flex items-center gap-2 rounded-full bg-destructive px-4 py-2 text-destructive-foreground shadow-lg">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm font-medium">Connection error</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-destructive-foreground hover:bg-white/20"
            onClick={handleReconnect}
          >
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  )
}
```

#### 4.2 Add to App Layout

**File:** `src/components/layout/AppShell.tsx` (add to existing)

```tsx
import { ConnectionStatusBanner } from '@/components/ui/ConnectionStatusBanner'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="...">
      {/* ... existing layout ... */}
      {children}
      <ConnectionStatusBanner />
    </div>
  )
}
```

---

### Phase 5: Query Error Handling

**Goal:** Centralize error handling for React Query failures.

#### 5.1 Create Query Error Handler Hook

**File:** `src/hooks/useQueryErrorHandler.ts`

```typescript
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { handleError } from '@/lib/errorHandler'
import { categorizeError } from '@/lib/errors'

/**
 * Global handler for React Query errors
 * Place this once in your app (e.g., in App.tsx or a provider)
 */
export function useGlobalQueryErrorHandler() {
  const queryClient = useQueryClient()
  const handledErrors = useRef(new Set<string>())

  useEffect(() => {
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      // Only handle new errors, not retries
      if (
        event.type === 'updated' &&
        event.query.state.status === 'error' &&
        event.query.state.fetchFailureCount === 1
      ) {
        const error = event.query.state.error
        const queryKey = JSON.stringify(event.query.queryKey)

        // Prevent duplicate handling
        if (handledErrors.current.has(queryKey)) return
        handledErrors.current.add(queryKey)

        // Clean up after a delay
        setTimeout(() => {
          handledErrors.current.delete(queryKey)
        }, 5000)

        // Categorize and handle
        const appError = categorizeError(error)

        // Auth errors - always handle (redirect to login)
        if (appError.category === 'auth') {
          handleError(error)
          return
        }

        // Network/server errors - show toast once
        if (appError.category === 'network' || appError.category === 'server') {
          handleError(error)
          return
        }

        // Other errors - let component handle via error state
        // (don't show global toast, component will show inline error)
      }
    })

    return unsubscribe
  }, [queryClient])
}
```

#### 5.2 Create Mutation Error Handler

**File:** `src/hooks/useMutationErrorHandler.ts`

```typescript
import { useMutation, type UseMutationOptions } from '@tanstack/react-query'
import { handleError } from '@/lib/errorHandler'
import type { AppError } from '@/lib/errors'

type MutationErrorHandlerOptions = {
  /** Show validation errors as toast instead of returning */
  showValidationToast?: boolean
  /** Custom error handler */
  onError?: (error: AppError) => void
}

/**
 * Wrapper around useMutation that adds consistent error handling
 */
export function useManagedMutation<TData, TError, TVariables, TContext>(
  options: UseMutationOptions<TData, TError, TVariables, TContext> & {
    errorHandling?: MutationErrorHandlerOptions
  }
) {
  const { errorHandling, onError, ...mutationOptions } = options

  return useMutation({
    ...mutationOptions,
    onError: (error, variables, context) => {
      // Handle error centrally
      const appError = handleError(error, {
        silent: !errorHandling?.showValidationToast && true,
        showDetails: errorHandling?.showValidationToast,
      })

      // Call custom handler if provided
      errorHandling?.onError?.(appError)

      // Call original onError if provided
      onError?.(error, variables, context)
    },
  })
}
```

---

### Phase 6: Notification Store Improvements

**Goal:** Better toast management with persistent errors.

#### 6.1 Create Dedicated Notification Store

**File:** `src/stores/notificationStore.ts`

```typescript
import { create } from 'zustand'

export interface Toast {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message?: string
  duration?: number  // 0 = persistent (no auto-dismiss)
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
```

---

### Phase 7: Update Components

**Goal:** Apply new error handling patterns to existing components.

#### 7.1 Update AlarmPanel Error Handling

**File:** `src/components/alarm/AlarmPanel.tsx` (modifications)

```typescript
// Before: Empty catch blocks
const handleCodeSubmit = useCallback(
  async (code: string) => {
    try {
      if (mode === 'arming' && pendingArmState) {
        await arm(pendingArmState, code)
      } else if (mode === 'disarming') {
        await disarm(code)
      }
      setShowKeypad(false)
      setMode('idle')
      setPendingArmState(null)
    } catch {
      // Error is handled by the store  <-- BAD: silent failure
    }
  },
  [mode, pendingArmState, arm, disarm]
)

// After: Explicit error handling
import { handleError } from '@/lib/errorHandler'

const handleCodeSubmit = useCallback(
  async (code: string) => {
    try {
      if (mode === 'arming' && pendingArmState) {
        await arm(pendingArmState, code)
      } else if (mode === 'disarming') {
        await disarm(code)
      }
      setShowKeypad(false)
      setMode('idle')
      setPendingArmState(null)
    } catch (error) {
      // Validation errors (wrong code) - keep modal open, show inline
      // Other errors - show toast
      const appError = handleError(error, { silent: true })

      if (appError.category === 'validation') {
        // Error already available via useAlarm().error
        // Modal stays open, user can retry
      } else {
        // Network/server error - show toast and close modal
        handleError(error)
        handleCancel()
      }
    }
  },
  [mode, pendingArmState, arm, disarm, handleCancel]
)
```

#### 7.2 Wrap Feature Sections

**File:** `src/pages/DashboardPage.tsx` (example)

```typescript
import { FeatureErrorBoundary } from '@/components/providers/FeatureErrorBoundary'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/types'

export function DashboardPage() {
  const queryClient = useQueryClient()

  const handleAlarmRetry = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
  }

  const handleSensorRetry = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
  }

  return (
    <div className="space-y-6 p-6">
      <FeatureErrorBoundary feature="Alarm Panel" onRetry={handleAlarmRetry}>
        <AlarmPanel />
      </FeatureErrorBoundary>

      <div className="grid gap-6 md:grid-cols-2">
        <FeatureErrorBoundary feature="System Status" variant="inline">
          <SystemStatusCard />
        </FeatureErrorBoundary>

        <FeatureErrorBoundary feature="Quick Links" variant="inline">
          <QuickLinksCard />
        </FeatureErrorBoundary>
      </div>
    </div>
  )
}
```

---

## File Structure Summary

```
src/
├── lib/
│   ├── errors.ts              # Error types and categorization
│   └── errorHandler.ts        # Central error handler
├── stores/
│   └── notificationStore.ts   # Toast/notification state
├── hooks/
│   ├── useErrorBoundary.ts    # Reset helper for error boundaries
│   ├── useQueryErrorHandler.ts    # Global query error handling
│   └── useMutationErrorHandler.ts # Mutation wrapper with error handling
├── components/
│   ├── providers/
│   │   ├── AppErrorBoundary.tsx      # (existing, keep as global fallback)
│   │   └── FeatureErrorBoundary.tsx  # NEW: Per-feature error boundary
│   └── ui/
│       └── ConnectionStatusBanner.tsx # NEW: Connection status UI
```

---

## Implementation Order

### Step 1: Foundation (lib/errors.ts, lib/errorHandler.ts)
Create the error type system and central handler.

### Step 2: Notification Store (stores/notificationStore.ts)
Replace or enhance existing toast system.

### Step 3: Feature Error Boundary (components/providers/FeatureErrorBoundary.tsx)
Create the reusable error boundary component.

### Step 4: Connection Status (components/ui/ConnectionStatusBanner.tsx)
Add visual feedback for connection state.

### Step 5: Query Error Handler (hooks/useQueryErrorHandler.ts)
Add to App.tsx for global query error handling.

### Step 6: Update Components
- Wrap major sections with FeatureErrorBoundary
- Replace empty catch blocks with handleError calls
- Add ConnectionStatusBanner to AppShell

---

## Testing Checklist

After implementation, verify these scenarios:

- [ ] **401 Error**: Redirects to /login with return path preserved
- [ ] **403 Error**: Shows permission denied message
- [ ] **400/422 Error**: Shows validation message, form stays open
- [ ] **500 Error**: Shows "server error" toast
- [ ] **Network Error**: Shows persistent connection banner
- [ ] **Component Crash**: Shows inline retry UI, rest of app works
- [ ] **WebSocket Disconnect**: Shows banner with reconnect button
- [ ] **Browser Offline**: Shows "no internet" banner
- [ ] **Reconnection**: Shows success message briefly
- [ ] **Duplicate Errors**: Same error doesn't create multiple toasts
