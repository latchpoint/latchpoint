import { useState } from 'react'
import { ChevronRight, ChevronDown, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface JsonTreeViewerProps {
  data: unknown
  defaultExpanded?: boolean
}

export function JsonTreeViewer({ data, defaultExpanded = true }: JsonTreeViewerProps) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard.writeText(JSON.stringify(data, null, 2)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="relative">
      <button
        onClick={handleCopy}
        className="absolute right-0 top-0 p-1 text-muted-foreground hover:text-foreground transition-colors"
        title="Copy JSON"
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <div className="font-mono text-sm">
        <JsonNode value={data} defaultExpanded={defaultExpanded} />
      </div>
    </div>
  )
}

interface JsonNodeProps {
  label?: string
  value: unknown
  defaultExpanded?: boolean
}

function JsonNode({ label, value, defaultExpanded = false }: JsonNodeProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  if (value === null) {
    return (
      <div className="flex items-baseline gap-1.5">
        {label != null && <span className="text-muted-foreground">{label}:</span>}
        <span className="italic text-muted-foreground">null</span>
      </div>
    )
  }

  if (typeof value === 'string') {
    return (
      <div className="flex items-baseline gap-1.5">
        {label != null && <span className="text-muted-foreground">{label}:</span>}
        <span className="text-green-600 dark:text-green-400">"{value}"</span>
      </div>
    )
  }

  if (typeof value === 'number') {
    return (
      <div className="flex items-baseline gap-1.5">
        {label != null && <span className="text-muted-foreground">{label}:</span>}
        <span className="text-blue-600 dark:text-blue-400">{value}</span>
      </div>
    )
  }

  if (typeof value === 'boolean') {
    return (
      <div className="flex items-baseline gap-1.5">
        {label != null && <span className="text-muted-foreground">{label}:</span>}
        <span className="text-orange-600 dark:text-orange-400">{String(value)}</span>
      </div>
    )
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <div className="flex items-baseline gap-1.5">
          {label != null && <span className="text-muted-foreground">{label}:</span>}
          <span className="text-muted-foreground">[]</span>
        </div>
      )
    }

    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-0.5 text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          {label != null && <span>{label}:</span>}
          <span className="text-xs">Array({value.length})</span>
        </button>
        {expanded && (
          <div className="ml-4 border-l border-border pl-3 space-y-0.5">
            {value.map((item, i) => (
              <JsonNode key={i} label={String(i)} value={item} />
            ))}
          </div>
        )}
      </div>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) {
      return (
        <div className="flex items-baseline gap-1.5">
          {label != null && <span className="text-muted-foreground">{label}:</span>}
          <span className="text-muted-foreground">{'{}'}</span>
        </div>
      )
    }

    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className={cn(
            'flex items-center gap-0.5 text-muted-foreground hover:text-foreground transition-colors',
            label == null && 'hidden'
          )}
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          {label != null && <span>{label}:</span>}
          <span className="text-xs">{`{${entries.length}}`}</span>
        </button>
        {(expanded || label == null) && (
          <div className={cn(label != null && 'ml-4 border-l border-border pl-3', 'space-y-0.5')}>
            {entries.map(([key, val]) => (
              <JsonNode key={key} label={key} value={val} />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-baseline gap-1.5">
      {label != null && <span className="text-muted-foreground">{label}:</span>}
      <span>{String(value)}</span>
    </div>
  )
}
