import { useState } from 'react'
import { RefreshCw } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { LoadingInline } from '@/components/ui/loading-inline'
import { SectionCard } from '@/components/ui/section-card'
import { getErrorMessage } from '@/types/errors'
import type { FrigateDetection } from '@/types'
import { FrigateDetectionDetailDialog } from './FrigateDetectionDetailDialog'

type Props = {
  isAdmin: boolean
  isLoading: boolean
  isFetching?: boolean
  error: unknown
  detections: FrigateDetection[] | undefined
  onRefresh?: () => void
}

export function FrigateRecentDetectionsCard({ isAdmin, isLoading, isFetching, error, detections, onRefresh }: Props) {
  const [selectedDetectionId, setSelectedDetectionId] = useState<number | null>(null)
  const [pageIndex, setPageIndex] = useState(0)
  const pageSize = 5

  const total = detections?.length ?? 0
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const safePageIndex = Math.min(pageIndex, pageCount - 1)
  const start = safePageIndex * pageSize
  const end = start + pageSize
  const pageItems = (detections ?? []).slice(start, end)

  const actions = isAdmin && onRefresh ? (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => {
        setSelectedDetectionId(null)
        setPageIndex(0)
        onRefresh()
      }}
      disabled={isFetching}
      className="gap-1"
    >
      <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
      Refresh
    </Button>
  ) : undefined

  return (
    <SectionCard title="Recent detections" description="Debug view of recently ingested person detections (admin-only). Click to view full event JSON." actions={actions}>
      {!isAdmin ? (
        <div className="text-sm text-muted-foreground">Only admins can view recent detections.</div>
      ) : isLoading ? (
        <LoadingInline label="Loading Frigate detections…" />
      ) : error ? (
        <Alert variant="error">
          <AlertDescription>{getErrorMessage(error) || 'Failed to load Frigate detections.'}</AlertDescription>
        </Alert>
      ) : (detections?.length ?? 0) === 0 ? (
        <div className="text-sm text-muted-foreground">No detections ingested yet.</div>
      ) : (
        <>
          <div className="space-y-2">
            {pageItems.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => setSelectedDetectionId(d.id)}
                className="w-full cursor-pointer rounded-md border border-border p-2 text-left text-sm transition-colors hover:bg-muted/50"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{d.camera}</div>
                  <div className="text-xs text-muted-foreground">{new Date(d.observedAt).toLocaleString()}</div>
                </div>
                <div className="text-xs text-muted-foreground">
                  Confidence: {Math.round(d.confidencePct)}%{d.eventId ? ` • Event: ${d.eventId}` : ''}
                </div>
              </button>
            ))}
          </div>

          {total > pageSize ? (
            <div className="mt-3 flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">
                Page {safePageIndex + 1} of {pageCount}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSelectedDetectionId(null)
                    setPageIndex((p) => Math.max(0, p - 1))
                  }}
                  disabled={safePageIndex === 0}
                >
                  Prev
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSelectedDetectionId(null)
                    setPageIndex((p) => Math.min(pageCount - 1, p + 1))
                  }}
                  disabled={safePageIndex >= pageCount - 1}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}

          <FrigateDetectionDetailDialog
            detectionId={selectedDetectionId}
            onClose={() => setSelectedDetectionId(null)}
          />
        </>
      )}
    </SectionCard>
  )
}
