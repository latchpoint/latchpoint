import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const pillVariants = cva(
  'inline-flex items-center rounded-full border border-input bg-background px-2 py-0.5 text-xs text-muted-foreground',
  {
    variants: {
      variant: {
        default: '',
        muted: 'bg-muted/30',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export interface PillProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof pillVariants> {}

export function Pill({ className, variant, ...props }: PillProps) {
  return <span className={cn(pillVariants({ variant }), className)} {...props} />
}

