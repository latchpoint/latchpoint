import * as React from 'react'

import { cn } from '@/lib/utils'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type CenteredCardLayout = 'screen' | 'section'

export interface CenteredCardProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  layout?: CenteredCardLayout
  title: React.ReactNode
  description?: React.ReactNode
  icon?: React.ReactNode
  cardClassName?: string
  containerClassName?: string
}

export function CenteredCard({
  layout = 'screen',
  title,
  description,
  icon,
  className,
  cardClassName,
  containerClassName,
  children,
  ...props
}: CenteredCardProps) {
  const containerBase =
    layout === 'screen'
      ? 'flex min-h-screen items-center justify-center bg-background p-4'
      : 'flex min-h-[70vh] items-center justify-center'

  return (
    <div className={cn(containerBase, containerClassName)}>
      <Card className={cn('w-full max-w-md', cardClassName)}>
        <CardHeader className={cn('text-center', className)} {...props}>
          {icon ? (
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground">
              {icon}
            </div>
          ) : null}
          <CardTitle className="text-2xl">{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  )
}
