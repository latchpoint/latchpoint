import * as React from 'react'

import { cn } from '@/lib/utils'
import { Spinner } from '@/components/ui/spinner'

export interface LoadingInlineProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: string
}

export function LoadingInline({ label = 'Loading…', className, ...props }: LoadingInlineProps) {
  return (
    <div className={cn('flex items-center gap-2 text-muted-foreground', className)} {...props}>
      <Spinner size="sm" aria-label={label} />
      <span>{label}</span>
    </div>
  )
}

