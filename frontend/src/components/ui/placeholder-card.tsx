import * as React from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export interface PlaceholderCardProps {
  title: React.ReactNode
  message: React.ReactNode
}

export function PlaceholderCard({ title, message }: PlaceholderCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  )
}

