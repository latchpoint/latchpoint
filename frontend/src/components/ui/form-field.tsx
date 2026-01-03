import * as React from 'react'

import { cn } from '@/lib/utils'
import { HelpTip } from '@/components/ui/help-tip'

export interface FormFieldProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: React.ReactNode
  htmlFor?: string
  description?: React.ReactNode
  help?: string
  error?: React.ReactNode
  required?: boolean
  size?: 'default' | 'compact'
}

export function FormField({
  label,
  htmlFor,
  description,
  help,
  error,
  required,
  size = 'default',
  className,
  children,
  ...props
}: FormFieldProps) {
  const helpId = React.useId()
  const descriptionId = React.useId()
  const errorId = React.useId()

  const describedBy = [
    description ? descriptionId : null,
    error ? errorId : null,
    help ? helpId : null,
  ]
    .filter(Boolean)
    .join(' ')

  const containerSpacing = size === 'compact' ? 'space-y-1' : 'space-y-2'
  const labelClassName = size === 'compact' ? 'text-xs text-muted-foreground' : 'text-sm font-medium'
  const descriptionClassName = size === 'compact' ? 'text-xs text-muted-foreground' : 'text-sm text-muted-foreground'
  const errorClassName = size === 'compact' ? 'text-xs text-destructive' : 'text-sm text-destructive'

  return (
    <div className={cn(containerSpacing, className)} {...props}>
      {label ? (
        <div className="flex items-center gap-2">
          <label
            className={labelClassName}
            htmlFor={htmlFor}
            aria-describedby={describedBy || undefined}
          >
            {label}
            {required ? <span className="ml-1 text-destructive">*</span> : null}
          </label>
          {help ? <HelpTip content={help} /> : null}
        </div>
      ) : null}

      <div>{children}</div>

      {description ? (
        <div id={descriptionId} className={descriptionClassName}>
          {description}
        </div>
      ) : null}
      {help && !label ? (
        <div id={helpId} className="text-xs text-muted-foreground">
          {help}
        </div>
      ) : null}
      {error ? (
        <div id={errorId} className={errorClassName}>
          {error}
        </div>
      ) : null}
    </div>
  )
}
