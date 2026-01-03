import * as React from 'react'

import { cn } from '@/lib/utils'

export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: React.ReactNode
  description?: React.ReactNode
}

export function EmptyState({ title, description, className, ...props }: EmptyStateProps) {
  return (
    <div className={cn('rounded-md border border-dashed p-4 text-center', className)} {...props}>
      {title ? <div className="font-medium">{title}</div> : null}
      {description ? <div className="mt-1 text-sm text-muted-foreground">{description}</div> : null}
    </div>
  )
}
