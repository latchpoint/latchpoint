/**
 * Click-to-insert chip row + help tooltip for rule notification message
 * template variables (ADR-0088).
 *
 * Renders under the Message and Title inputs in `SendNotificationFields`.
 * Each chip inserts its token at the textarea / input cursor; the trailing
 * `?` HelpTip shows the full variable reference.
 */
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { cn } from '@/lib/utils'

import { TEMPLATE_VARIABLE_CHIPS, TEMPLATE_VARIABLES } from '@/features/rules/templateVariables'

export interface TemplateVariablePickerProps {
  /** Ref to the input or textarea element the chips insert into. */
  inputRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement | null>
  /** Current value of the field; needed to splice the token at the cursor. */
  value: string
  /** Called with the new value after a chip insertion. */
  onChange: (next: string) => void
  /** Disable chips when the parent form is disabled. */
  disabled?: boolean
  className?: string
}

export function TemplateVariablePicker({
  inputRef,
  value,
  onChange,
  disabled,
  className,
}: TemplateVariablePickerProps) {
  const insert = React.useCallback(
    (token: string) => {
      const el = inputRef.current
      // Fall back to appending if we cannot read the selection (the input may
      // not be focused yet, especially on first render).
      const start = el?.selectionStart ?? value.length
      const end = el?.selectionEnd ?? value.length
      const next = value.slice(0, start) + token + value.slice(end)
      onChange(next)
      if (el) {
        // Restore cursor to just after the inserted token, on the next tick
        // so the controlled value has settled.
        const cursor = start + token.length
        requestAnimationFrame(() => {
          el.focus()
          el.setSelectionRange(cursor, cursor)
        })
      }
    },
    [inputRef, onChange, value]
  )

  return (
    <div className={cn('flex flex-wrap items-center gap-1', className)}>
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Insert</span>
      {TEMPLATE_VARIABLE_CHIPS.map((v) => (
        <Button
          key={v.token}
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => insert(v.token)}
          className="h-6 px-2 text-[11px] font-mono"
          aria-label={`Insert ${v.token}`}
        >
          {v.label}
        </Button>
      ))}
      <HelpTip
        side="top"
        label="Available template variables"
        content={
          <div className="max-w-xs space-y-1.5 text-left text-xs">
            <p className="font-medium">Available variables</p>
            <ul className="space-y-1">
              {TEMPLATE_VARIABLES.map((v) => (
                <li key={v.token}>
                  <code className="text-[10px]">{v.token}</code>
                  <div className="text-muted-foreground">{v.description}</div>
                  <div className="text-muted-foreground">
                    e.g. <span className="italic">{v.example}</span>
                  </div>
                </li>
              ))}
            </ul>
            <p className="pt-1 text-muted-foreground">
              Unknown variables are shipped literally, so a typo is visible in the delivered notification.
            </p>
          </div>
        }
      />
    </div>
  )
}
