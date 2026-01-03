import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Check } from 'lucide-react'

import { Modal } from '@/components/ui/modal'
import { Button } from '@/components/ui/button'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { frigateService } from '@/services/frigate'
import { getErrorMessage } from '@/types/errors'

type Props = {
  detectionId: number | null
  onClose: () => void
}

export function FrigateDetectionDetailDialog({ detectionId, onClose }: Props) {
  const [copied, setCopied] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['frigate', 'detection', detectionId],
    queryFn: () => frigateService.getDetection(detectionId!),
    enabled: detectionId !== null,
  })

  const handleCopy = async () => {
    if (!data?.raw) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(data.raw, null, 2))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API not available
    }
  }

  return (
    <Modal
      open={detectionId !== null}
      onOpenChange={(open) => !open && onClose()}
      title="Detection Event Details"
      description={data ? `Camera: ${data.camera} | Confidence: ${Math.round(data.confidencePct)}%` : undefined}
      maxWidthClassName="max-w-2xl"
    >
      {isLoading ? (
        <LoadingInline label="Loading detection details..." />
      ) : error ? (
        <Alert variant="error">
          <AlertDescription>{getErrorMessage(error) || 'Failed to load detection details.'}</AlertDescription>
        </Alert>
      ) : data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-muted-foreground">Event ID:</span>
              <span className="ml-2 font-mono text-xs">{data.eventId || '(none)'}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Label:</span>
              <span className="ml-2">{data.label}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Observed:</span>
              <span className="ml-2">{new Date(data.observedAt).toLocaleString()}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Provider:</span>
              <span className="ml-2">{data.provider}</span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Raw Event JSON</span>
              <Button type="button" variant="outline" size="sm" onClick={handleCopy} className="gap-1">
                {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs">
              {JSON.stringify(data.raw, null, 2)}
            </pre>
          </div>
        </div>
      ) : null}
    </Modal>
  )
}
