import type { ReactNode } from 'react'
import { SectionCard } from '@/components/ui/section-card'

type Props = {
  title?: ReactNode
  description?: ReactNode
  children: ReactNode
}

export function IntegrationConnectionCard({ title = 'Connection / setup', description, children }: Props) {
  return (
    <SectionCard title={title} description={description}>
      {children}
    </SectionCard>
  )
}

