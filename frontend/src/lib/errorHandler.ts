import { categorizeError, type AppError } from './errors'
import { useNotificationStore } from '@/stores/notificationStore'

type ErrorHandlerOptions = {
  silent?: boolean // Don't show toast
  showDetails?: boolean // Show field-level details
  onAuth?: () => void // Custom auth error handler
  onRetry?: () => void // Retry callback for recoverable errors
}

/**
 * Central error handler that routes errors to appropriate UI feedback
 */
export function handleError(error: unknown, options: ErrorHandlerOptions = {}): AppError {
  const appError = categorizeError(error)

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

function handleAuthError(_appError: AppError, options: ErrorHandlerOptions) {
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

function handleValidationError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  // If we have field details and showDetails is true, format them
  if (appError.details && options.showDetails) {
    const detailMessages = Object.entries(appError.details)
      .map(([field, messages]) => `${field}: ${messages.join(', ')}`)
      .join('\n')

    addToast({
      type: 'warning',
      title: 'Validation Error',
      message: detailMessages || appError.message,
    })
  } else {
    addToast({
      type: 'warning',
      title: 'Validation Error',
      message: appError.message,
    })
  }
}

function handleNetworkError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Connection Error',
    message: appError.message,
    duration: 0, // Don't auto-dismiss network errors
  })
}

function handleServerError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Server Error',
    message: appError.message,
  })
}

function handleTimeoutError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'warning',
    title: 'Request Timeout',
    message: appError.message,
  })
}

function handleNotFoundError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'warning',
    title: 'Not Found',
    message: appError.message,
  })
}

function handleUnknownError(appError: AppError, options: ErrorHandlerOptions) {
  if (options.silent) return

  const { addToast } = useNotificationStore.getState()

  addToast({
    type: 'error',
    title: 'Error',
    message: appError.message,
  })
}

/**
 * Create a wrapped async function that automatically handles errors
 * Returns a function with the same signature as the input
 */
export function withErrorHandling<
  TArgs extends unknown[],
  TReturn
>(
  fn: (...args: TArgs) => Promise<TReturn>,
  options: ErrorHandlerOptions = {}
): (...args: TArgs) => Promise<TReturn> {
  return async (...args: TArgs): Promise<TReturn> => {
    try {
      return await fn(...args)
    } catch (error) {
      handleError(error, options)
      throw error // Re-throw for component-level handling if needed
    }
  }
}
