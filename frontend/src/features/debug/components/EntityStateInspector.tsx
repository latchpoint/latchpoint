import { useState, useMemo } from 'react'
import { SectionCard } from '@/components/ui/section-card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { useEntitiesQuery } from '@/hooks'
import { useRelativeTime } from '../hooks/useRelativeTime'
import { useEntityLiveState } from '../hooks/useEntityLiveState'
import { JsonTreeViewer } from './JsonTreeViewer'
import { cn } from '@/lib/utils'
import type { Entity } from '@/types'

function FieldHighlight({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'transition-colors duration-500 rounded px-1 -mx-1',
        active && 'bg-yellow-200/60 dark:bg-yellow-500/20'
      )}
    >
      {children}
    </span>
  )
}

function EntityDetail({ entity }: { entity: Entity }) {
  const changedFields = useEntityLiveState(entity.entityId)
  const lastChanged = useRelativeTime(entity.lastChanged)
  const lastSeen = useRelativeTime(entity.lastSeen)

  const fields = [
    { label: 'Entity ID', key: 'entityId', value: <code className="text-sm">{entity.entityId}</code> },
    { label: 'Name', key: 'name', value: entity.name },
    { label: 'Domain', key: 'domain', value: entity.domain },
    { label: 'Device Class', key: 'deviceClass', value: entity.deviceClass || '—' },
    {
      label: 'State',
      key: 'lastState',
      value: <Badge variant="secondary">{entity.lastState ?? 'unknown'}</Badge>,
    },
    { label: 'Source', key: 'source', value: entity.source },
    { label: 'Last Changed', key: 'lastChanged', value: lastChanged },
    { label: 'Last Seen', key: 'lastSeen', value: lastSeen },
  ]

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {fields.map((f) => (
          <div key={f.key} className="contents">
            <dt className="text-muted-foreground font-medium">{f.label}</dt>
            <dd>
              <FieldHighlight active={changedFields.has(f.key)}>{f.value}</FieldHighlight>
            </dd>
          </div>
        ))}
      </dl>

      {entity.attributes && Object.keys(entity.attributes).length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Attributes</h4>
          <div className="rounded-md border bg-muted/40 p-3">
            <JsonTreeViewer data={entity.attributes} />
          </div>
        </div>
      )}
    </div>
  )
}

export function EntityStateInspector() {
  const { data: entities, isLoading } = useEntitiesQuery()
  const [search, setSearch] = useState('')
  const [domainFilter, setDomainFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const domains = useMemo(() => {
    if (!entities) return []
    return [...new Set(entities.map((e) => e.domain))].sort()
  }, [entities])

  const sources = useMemo(() => {
    if (!entities) return []
    return [...new Set(entities.map((e) => e.source))].sort()
  }, [entities])

  const filtered = useMemo(() => {
    if (!entities) return []
    const q = search.toLowerCase()
    return entities.filter((e) => {
      if (domainFilter && e.domain !== domainFilter) return false
      if (sourceFilter && e.source !== sourceFilter) return false
      if (q && !e.entityId.toLowerCase().includes(q) && !e.name.toLowerCase().includes(q)) return false
      return true
    })
  }, [entities, search, domainFilter, sourceFilter])

  const selectedEntity = useMemo(() => {
    if (!selectedId || !entities) return null
    return entities.find((e) => e.entityId === selectedId) ?? null
  }, [entities, selectedId])

  return (
    <SectionCard title="Entity State Inspector" description="Select an entity to inspect its current state and attributes.">
      <div className="space-y-4">
        {/* Filters */}
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            type="text"
            placeholder="Search entities..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="sm:w-1/2"
          />
          <Select
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            size="sm"
            className="sm:w-1/4"
          >
            <option value="">All domains</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
          <Select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            size="sm"
            className="sm:w-1/4"
          >
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </div>

        {/* Entity list */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading entities...</p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground">No entities found.</p>
        ) : (
          <div className="max-h-48 overflow-y-auto rounded-md border">
            {filtered.map((e) => (
              <button
                key={e.entityId}
                onClick={() => setSelectedId(e.entityId)}
                className={cn(
                  'flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted/50 transition-colors',
                  selectedId === e.entityId && 'bg-muted'
                )}
              >
                <span className="truncate">{e.entityId}</span>
                <Badge variant="outline" className="shrink-0 text-xs">
                  {e.lastState ?? '—'}
                </Badge>
              </button>
            ))}
          </div>
        )}

        {/* Detail panel */}
        {selectedEntity && (
          <div className="rounded-md border p-4">
            <EntityDetail entity={selectedEntity} />
          </div>
        )}
      </div>
    </SectionCard>
  )
}
