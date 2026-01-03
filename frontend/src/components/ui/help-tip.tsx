import * as React from 'react'
import { Info } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Tooltip } from '@/components/ui/tooltip'

export interface HelpTipProps extends Omit<React.ComponentProps<typeof Tooltip>, 'children'> {
  label?: string
  className?: string
}

export function HelpTip({ content, side = 'top', label = 'Help', className }: HelpTipProps) {
  return (
    <Tooltip content={content} side={side}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          'inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
          className
        )}
      >
        <Info className="h-4 w-4" />
      </button>
    </Tooltip>
  )
}

