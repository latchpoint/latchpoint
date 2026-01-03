import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const alertVariants = cva('w-full rounded-lg border', {
  variants: {
    variant: {
      info: 'border-border bg-muted/30 text-foreground',
      success:
        'border-success/30 bg-success/10 text-success dark:border-success/50 dark:bg-success/20 dark:text-success',
      warning:
        'border-warning/30 bg-warning/10 text-warning dark:border-warning/50 dark:bg-warning/20 dark:text-warning',
      error: 'border-destructive/30 bg-destructive/10 text-destructive',
    },
    layout: {
      banner: 'p-4',
      inline: 'p-3 text-sm',
    },
  },
  defaultVariants: {
    variant: 'info',
    layout: 'banner',
  },
})

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant, layout, ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      className={cn(alertVariants({ variant, layout }), className)}
      {...props}
    />
  )
)
Alert.displayName = 'Alert'

const AlertTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h5
    ref={ref}
    className={cn('mb-1 font-medium leading-none tracking-tight', className)}
    {...props}
  />
))
AlertTitle.displayName = 'AlertTitle'

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('text-sm leading-relaxed', className)} {...props} />
))
AlertDescription.displayName = 'AlertDescription'

export { Alert, AlertTitle, AlertDescription }
