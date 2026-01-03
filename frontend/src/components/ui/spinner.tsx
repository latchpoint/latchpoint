import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const spinnerVariants = cva(
  'inline-block animate-spin rounded-full border-2 border-muted-foreground/20 border-t-primary',
  {
    variants: {
      size: {
        sm: 'h-4 w-4',
        md: 'h-6 w-6',
        lg: 'h-8 w-8',
      },
    },
    defaultVariants: {
      size: 'md',
    },
  }
)

export interface SpinnerProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'children'>,
    VariantProps<typeof spinnerVariants> {
  fullscreen?: boolean
  label?: string
}

export function Spinner({
  size,
  fullscreen = false,
  label = 'Loading',
  className,
  ...props
}: SpinnerProps) {
  const indicator = (
    <div
      role="status"
      aria-label={label}
      className={cn(spinnerVariants({ size }), className)}
      {...props}
    />
  )

  if (fullscreen) {
    return <div className="flex min-h-screen items-center justify-center">{indicator}</div>
  }

  return indicator
}

