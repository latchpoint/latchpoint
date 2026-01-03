import * as React from 'react'
import { PageHeader, type PageHeaderProps } from '@/components/ui/page-header'
import { cn } from '@/lib/utils'

type PageProps = Pick<PageHeaderProps, 'title' | 'description' | 'actions'> & {
  children: React.ReactNode
  className?: string
}

export function Page({ title, description, actions, children, className }: PageProps) {
  return (
    <div className={cn('space-y-6', className)}>
      <PageHeader title={title} description={description} actions={actions} />
      {children}
    </div>
  )
}

export default Page

