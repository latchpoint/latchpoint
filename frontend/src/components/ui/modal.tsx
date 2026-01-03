import * as React from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export interface ModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
  contentClassName?: string
  showCloseButton?: boolean
  closeOnBackdrop?: boolean
  closeOnEscape?: boolean
  maxWidthClassName?: string
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  contentClassName,
  showCloseButton = true,
  closeOnBackdrop = true,
  closeOnEscape = true,
  maxWidthClassName = 'max-w-md',
}: ModalProps) {
  React.useEffect(() => {
    if (!open || !closeOnEscape) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, closeOnEscape, onOpenChange])

  if (!open) return null

  return createPortal(
    <div className={cn('fixed inset-0 z-50', className)}>
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onMouseDown={() => {
          if (!closeOnBackdrop) return
          onOpenChange(false)
        }}
      />
      <div className="relative flex max-h-full items-center justify-center overflow-y-auto p-4">
        <Card className={cn('flex max-h-[calc(100vh-2rem)] w-full flex-col overflow-hidden', maxWidthClassName, contentClassName)}>
          {(title || description || showCloseButton) && (
            <CardHeader className={cn('flex-shrink-0', showCloseButton ? 'relative' : undefined)}>
              {title ? <CardTitle className="text-center">{title}</CardTitle> : null}
              {description ? <CardDescription>{description}</CardDescription> : null}
              {showCloseButton ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-2 top-2"
                  onClick={() => onOpenChange(false)}
                  aria-label="Close"
                >
                  <X className="h-4 w-4" />
                </Button>
              ) : null}
            </CardHeader>
          )}
          <CardContent className="overflow-y-auto">{children}</CardContent>
        </Card>
      </div>
    </div>,
    document.body
  )
}

