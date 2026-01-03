import * as React from 'react'

import { cn } from '@/lib/utils'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export interface SectionCardProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  contentClassName?: string
}

export function SectionCard({
  title,
  description,
  actions,
  className,
  contentClassName,
  children,
  ...props
}: SectionCardProps) {
  return (
    <Card className={className} {...props}>
      {(title || description || actions) && (
        <CardHeader
          className={cn(actions ? 'space-y-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0' : undefined)}
        >
          <div className={cn(actions ? 'space-y-1.5' : undefined)}>
            {title ? <CardTitle>{title}</CardTitle> : null}
            {description ? <CardDescription>{description}</CardDescription> : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap gap-2 sm:ml-4">{actions}</div> : null}
        </CardHeader>
      )}
      <CardContent className={contentClassName}>{children}</CardContent>
    </Card>
  )
}
