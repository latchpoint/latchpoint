import { useState, useCallback } from 'react'
import { Delete, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface KeypadProps {
  onSubmit: (code: string) => void
  onCancel?: () => void
  disabled?: boolean
  maxLength?: number
  showCancel?: boolean
  submitLabel?: string
}

const KEYPAD_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', ''] as const

export function Keypad({
  onSubmit,
  onCancel,
  disabled = false,
  maxLength = 8,
  showCancel = true,
  submitLabel = 'Submit',
}: KeypadProps) {
  const [code, setCode] = useState('')

  const handleKeyPress = useCallback(
    (key: string) => {
      if (disabled) return
      if (code.length < maxLength) {
        setCode((prev) => prev + key)
      }
    },
    [code.length, maxLength, disabled]
  )

  const handleDelete = useCallback(() => {
    if (disabled) return
    setCode((prev) => prev.slice(0, -1))
  }, [disabled])

  const handleClear = useCallback(() => {
    if (disabled) return
    setCode('')
  }, [disabled])

  const handleSubmit = useCallback(() => {
    if (disabled || code.length === 0) return
    onSubmit(code)
    setCode('')
  }, [code, disabled, onSubmit])

  const handleCancel = useCallback(() => {
    setCode('')
    onCancel?.()
  }, [onCancel])

  return (
    <div className="w-full max-w-xs mx-auto">
      {/* Code Display */}
      <div className="mb-4">
        <div
          className={cn(
            'h-14 flex items-center justify-center rounded-lg border-2 bg-muted/50 text-2xl font-mono tracking-widest',
            code.length > 0 ? 'border-primary' : 'border-border'
          )}
        >
          {code.length > 0 ? '•'.repeat(code.length) : (
            <span className="text-muted-foreground text-base">Enter code</span>
          )}
        </div>
      </div>

      {/* Keypad Grid */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        {KEYPAD_KEYS.map((key, index) => {
          if (key === '') {
            // Empty cell or special button position
            if (index === 9) {
              // Clear button position
              return (
                <Button
                  key="clear"
                  variant="outline"
                  className="h-16 text-lg"
                  onClick={handleClear}
                  disabled={disabled || code.length === 0}
                >
                  Clear
                </Button>
              )
            }
            // Delete button position (index 11)
            return (
              <Button
                key="delete"
                variant="outline"
                className="h-16"
                onClick={handleDelete}
                disabled={disabled || code.length === 0}
              >
                <Delete className="h-6 w-6" />
              </Button>
            )
          }
          return (
            <Button
              key={key}
              variant="secondary"
              className="h-16 text-2xl font-semibold"
              onClick={() => handleKeyPress(key)}
              disabled={disabled}
            >
              {key}
            </Button>
          )
        })}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        {showCancel && onCancel && (
          <Button
            variant="outline"
            className="flex-1 h-12"
            onClick={handleCancel}
            disabled={disabled}
          >
            Cancel
          </Button>
        )}
        <Button
          className="flex-1 h-12"
          onClick={handleSubmit}
          disabled={disabled || code.length === 0}
        >
          <Check className="h-5 w-5 mr-2" />
          {submitLabel}
        </Button>
      </div>
    </div>
  )
}

export default Keypad
