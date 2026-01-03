import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'

type Props = {
  selectedCount: number
  isSubmitting: boolean
  progress: { current: number; total: number } | null
  onSubmit: () => void
}

export function ImportSubmitBar({ selectedCount, isSubmitting, progress, onSubmit }: Props) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-sm text-muted-foreground">
        Selected: {selectedCount}
        {progress ? ` • Importing ${progress.current}/${progress.total}` : ''}
      </div>
      <Button type="button" disabled={isSubmitting || selectedCount === 0} onClick={onSubmit}>
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Importing…
          </>
        ) : (
          'Import selected'
        )}
      </Button>
    </div>
  )
}

