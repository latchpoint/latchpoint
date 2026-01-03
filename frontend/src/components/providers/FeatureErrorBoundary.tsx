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
