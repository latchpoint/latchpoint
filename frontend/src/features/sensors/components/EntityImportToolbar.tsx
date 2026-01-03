import { Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export type EntityImportViewMode = 'available' | 'imported' | 'all'

type Props = {
  query: string
  onQueryChange: (next: string) => void
  viewMode: EntityImportViewMode
  onViewModeChange: (next: EntityImportViewMode) => void
  availableCount: number
  importedCount: number
  allCount: number
}

export function EntityImportToolbar({
  query,
  onQueryChange,
  viewMode,
  onViewModeChange,
  availableCount,
  importedCount,
  allCount,
}: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="relative w-full md:max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search by name or entity_id…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">View</span>
        <Button
          type="button"
          size="sm"
          variant={viewMode === 'available' ? 'secondary' : 'outline'}
          onClick={() => onViewModeChange('available')}
        >
          Available ({availableCount})
        </Button>
        <Button
          type="button"
          size="sm"
          variant={viewMode === 'imported' ? 'secondary' : 'outline'}
          onClick={() => onViewModeChange('imported')}
        >
          Imported ({importedCount})
        </Button>
        <Button
          type="button"
          size="sm"
          variant={viewMode === 'all' ? 'secondary' : 'outline'}
          onClick={() => onViewModeChange('all')}
        >
          All ({allCount})
        </Button>
      </div>
    </div>
  )
}

