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
 *
 * Note: This is a convenience wrapper. Due to TypeScript complexity with
 * generic mutation options, it's often simpler to use handleError directly
 * in mutation onError callbacks.
 */
export function useManagedMutation<TData = unknown, TError = Error, TVariables = void, TContext = unknown>(
  options: UseMutationOptions<TData, TError, TVariables, TContext> & {
    errorHandling?: MutationErrorHandlerOptions
  }
) {
  const { errorHandling, onError: originalOnError, ...mutationOptions } = options

  return useMutation<TData, TError, TVariables, TContext>({
    ...mutationOptions,
    onError: (error, variables, context) => {
      // Handle error centrally
      const appError = handleError(error, {
        silent: !errorHandling?.showValidationToast,
        showDetails: errorHandling?.showValidationToast,
      })

      // Call custom handler if provided
      errorHandling?.onError?.(appError)

      // Call original onError if provided (using type assertion to handle TanStack Query version differences)
      if (originalOnError) {
        ;(originalOnError as (error: TError, variables: TVariables, context: TContext | undefined) => void)(error, variables, context)
      }
    },
  })
}
