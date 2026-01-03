import { ShieldOff, ShieldAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface QuickActionsProps {
  onDisarm: () => void
  onPanic?: () => void
  onCancel?: () => void
  showDisarm?: boolean
  showPanic?: boolean
  showCancel?: boolean
  disabled?: boolean
  className?: string
}

export function QuickActions({
  onDisarm,
  onPanic,
  onCancel,
  showDisarm = true,
  showPanic = true,
  showCancel = false,
  disabled = false,
  className,
}: QuickActionsProps) {
  return (
    <div className={cn('flex gap-3', className)}>
      {showCancel && onCancel && (
        <Button
          variant="outline"
          className="flex-1 h-14"
          onClick={onCancel}
          disabled={disabled}
        >
          <X className="h-5 w-5 mr-2" />
          Cancel
        </Button>
      )}

      {showDisarm && (
        <Button
          variant="default"
          className="flex-1 h-14 bg-alarm-disarmed hover:bg-alarm-disarmed/90 text-white"
          onClick={onDisarm}
          disabled={disabled}
        >
          <ShieldOff className="h-5 w-5 mr-2" />
          Disarm
        </Button>
      )}

      {showPanic && onPanic && (
        <Button
          variant="destructive"
          className="h-14 px-6"
          onClick={onPanic}
          disabled={disabled}
        >
          <ShieldAlert className="h-5 w-5 mr-2" />
          Panic
        </Button>
      )}
    </div>
  )
}

export default QuickActions
