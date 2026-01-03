import { Component } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Props = {
  children: React.ReactNode
}

type State = {
  hasError: boolean
  errorMessage: string | null
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, errorMessage: null }

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : 'An unexpected error occurred.'
    return { hasError: true, errorMessage: message }
  }

  componentDidCatch(error: unknown) {
    // Keep minimal; console logging is still useful in dev.
    console.error('Unhandled UI error:', error)
  }

  private reset = () => {
    this.setState({ hasError: false, errorMessage: null })
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="min-h-screen bg-background p-6 flex items-center justify-center">
        <Card className="w-full max-w-xl">
          <CardHeader>
            <CardTitle>Something went wrong</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm text-muted-foreground">
              The app hit an unexpected error while rendering this page.
            </div>
            {this.state.errorMessage && (
              <pre className="rounded-md border bg-muted/30 p-3 text-xs overflow-auto">
                {this.state.errorMessage}
              </pre>
            )}
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={this.reset}>
                Try again
              </Button>
              <Button type="button" variant="outline" onClick={() => window.location.reload()}>
                Reload page
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }
}

export default AppErrorBoundary
