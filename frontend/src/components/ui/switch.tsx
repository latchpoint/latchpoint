import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const switchVariants = cva(
  'inline-flex items-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      size: {
        sm: 'h-5 w-9',
        md: 'h-6 w-11',
      },
    },
    defaultVariants: {
      size: 'sm',
    },
  }
)

export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'>,
    VariantProps<typeof switchVariants> {
  checked: boolean
  onCheckedChange?: (checked: boolean) => void
}

export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ className, checked, onCheckedChange, disabled, size, ...props }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        data-state={checked ? 'checked' : 'unchecked'}
        disabled={disabled}
        onClick={() => {
          if (disabled) return
          onCheckedChange?.(!checked)
        }}
        className={cn(
          switchVariants({ size }),
          checked ? 'bg-primary border-primary' : 'bg-muted/40 border-input',
          className
        )}
        {...props}
      >
        <span
          aria-hidden="true"
          className={cn(
            'pointer-events-none block rounded-full bg-background shadow transition-transform',
            size === 'md' ? 'h-5 w-5' : 'h-4 w-4',
            checked ? (size === 'md' ? 'translate-x-5' : 'translate-x-4') : 'translate-x-0.5'
          )}
        />
      </button>
    )
  }
)
Switch.displayName = 'Switch'

