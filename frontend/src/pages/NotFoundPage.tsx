import { Link } from 'react-router-dom'
import { Home } from 'lucide-react'
import { Routes } from '@/lib/constants'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center">
      <h1 className="text-6xl font-bold">404</h1>
      <p className="mt-4 text-xl text-muted-foreground">Page not found</p>
      <Button asChild className="mt-8">
        <Link to={Routes.HOME}>
          <Home className="mr-2 h-4 w-4" />
          Go Home
        </Link>
      </Button>
    </div>
  )
}

export default NotFoundPage
