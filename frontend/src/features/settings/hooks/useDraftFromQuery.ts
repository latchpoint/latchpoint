import { useEffect, useState } from 'react'

export function useDraftFromQuery<T>(initialDraft: T | null) {
  const [draft, setDraft] = useState<T | null>(null)

  useEffect(() => {
    if (!initialDraft) return
    queueMicrotask(() => setDraft((prev) => prev ?? initialDraft))
  }, [initialDraft])

  const resetToInitial = () => {
    setDraft(initialDraft)
  }

  return { draft, setDraft, resetToInitial }
}

