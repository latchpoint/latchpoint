import { useMemo, useState } from 'react'

import { Page } from '@/components/layout'
import { SectionCard } from '@/components/ui/section-card'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'
import {
  useControlPanelsQuery,
  useCreateControlPanelMutation,
  useDeleteControlPanelMutation,
  useTestControlPanelMutation,
  useUpdateControlPanelMutation,
} from '@/hooks/useControlPanels'
import { useZwavejsNodesQuery, useZwavejsStatusQuery } from '@/hooks/useZwavejs'

type PanelType = 'ring_keypad_v2_zwavejs'

const PANEL_TYPE_OPTIONS: Array<{ value: PanelType; label: string }> = [
  { value: 'ring_keypad_v2_zwavejs', label: 'Ring Keypad v2 (Z-Wave JS)' },
]

export function ControlPanelsPage() {
  const userQuery = useCurrentUserQuery()
  const isAdmin = userQuery.data?.role === UserRole.ADMIN

  const panelsQuery = useControlPanelsQuery()
  const zwaveStatusQuery = useZwavejsStatusQuery()
  const createMutation = useCreateControlPanelMutation()
  const updateMutation = useUpdateControlPanelMutation()
  const deleteMutation = useDeleteControlPanelMutation()

  const [isAdding, setIsAdding] = useState(false)
  const [panelType, setPanelType] = useState<PanelType>('ring_keypad_v2_zwavejs')

  const defaultHomeId = zwaveStatusQuery.data?.homeId ?? undefined
  const zwaveEnabled = Boolean(zwaveStatusQuery.data?.enabled)
  const canAddZwave = zwaveEnabled
  const nodesQuery = useZwavejsNodesQuery({
    enabled: isAdding && panelType === 'ring_keypad_v2_zwavejs' && canAddZwave,
  })
  const testMutation = useTestControlPanelMutation()

  const [name, setName] = useState('Ring Keypad v2')
  const [homeId, setHomeId] = useState<string>(defaultHomeId ? String(defaultHomeId) : '')
  const [nodeId, setNodeId] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string>('')
  const [showAllZwaveNodes, setShowAllZwaveNodes] = useState(false)
  const [beepVolumeDraftById, setBeepVolumeDraftById] = useState<Record<number, string>>({})

  const existingZwaveExternalKeys = useMemo(() => {
    const keys = new Map<string, { id: number; name: string }>()
    for (const device of panelsQuery.data ?? []) {
      if (device.integrationType !== 'zwavejs') continue
      const key = device.externalKey ?? ''
      if (!key.startsWith('zwavejs:')) continue
      keys.set(key, { id: device.id, name: device.name })
    }
    return keys
  }, [panelsQuery.data])

  const inferredHomeIdForFiltering = useMemo(() => {
    const trimmed = homeId.trim()
    if (trimmed === '') {
      if (defaultHomeId != null) return defaultHomeId
    } else {
      const parsed = Number(trimmed)
      if (Number.isFinite(parsed)) return parsed
    }
    const homeIds = new Set<number>()
    for (const key of existingZwaveExternalKeys.keys()) {
      const parts = key.split(':')
      if (parts.length !== 3) continue
      const h = Number(parts[1])
      if (Number.isFinite(h)) homeIds.add(h)
    }
    if (homeIds.size === 1) return Array.from(homeIds)[0]
    return null
  }, [defaultHomeId, existingZwaveExternalKeys, homeId])

  const zwaveExternalKeyForForm = useMemo(() => {
    const homeIdInt = inferredHomeIdForFiltering
    const nodeIdInt = Number(nodeId)
    if (homeIdInt == null || !Number.isFinite(nodeIdInt)) return null
    return `zwavejs:${homeIdInt}:${nodeIdInt}`
  }, [inferredHomeIdForFiltering, nodeId])

  const duplicatePanel = useMemo(() => {
    if (panelType !== 'ring_keypad_v2_zwavejs') return null
    if (!zwaveExternalKeyForForm) return null
    return existingZwaveExternalKeys.get(zwaveExternalKeyForForm) ?? null
  }, [existingZwaveExternalKeys, panelType, zwaveExternalKeyForForm])

  const nodesForPicker = useMemo(() => {
    const nodes = nodesQuery.data?.nodes ?? []
    if (showAllZwaveNodes) return { nodes, isFiltered: false, filterMatchedAny: true }

    const filtered = nodes.filter((n) => {
      const name = (n.name ?? '').toLowerCase()
      const manufacturer = (n.manufacturer ?? '').toLowerCase()
      const productLabel = (n.productLabel ?? '').toLowerCase()
      const haystack = `${name} ${manufacturer} ${productLabel}`
      return (
        manufacturer.includes('ring') ||
        haystack.includes('ring') ||
        haystack.includes('keypad') ||
        haystack.includes('alarm keypad')
      )
    })
    return filtered.length > 0
      ? { nodes: filtered, isFiltered: true, filterMatchedAny: true }
      : { nodes, isFiltered: true, filterMatchedAny: false }
  }, [nodesQuery.data?.nodes, showAllZwaveNodes])

  const canSubmit = useMemo(() => {
    if (!name.trim()) return false
    if (panelType === 'ring_keypad_v2_zwavejs') {
      if (!String(homeId).trim() || !String(nodeId).trim()) return false
      if (duplicatePanel) return false
    }
    return true
  }, [name, homeId, nodeId, panelType, duplicatePanel])

  const resetForm = () => {
    setPanelType('ring_keypad_v2_zwavejs')
    setName('Ring Keypad v2')
    setHomeId(defaultHomeId ? String(defaultHomeId) : '')
    setNodeId('')
    setSelectedNodeId('')
    setShowAllZwaveNodes(false)
  }

  const createPanel = async () => {
    if (panelType !== 'ring_keypad_v2_zwavejs') return
    const homeIdInt = Number(homeId)
    const nodeIdInt = Number(nodeId)
    if (!Number.isFinite(homeIdInt) || !Number.isFinite(nodeIdInt)) return

    await createMutation.mutateAsync({
      name: name.trim(),
      integrationType: 'zwavejs',
      kind: 'ring_keypad_v2',
      enabled: true,
      externalId: { home_id: homeIdInt, node_id: nodeIdInt },
    })

    setIsAdding(false)
    resetForm()
  }

  return (
    <Page title="Control Panels">
      <SectionCard
        title="Configured panels"
        description="If no panels are configured, add one below. Code validation uses the app's codes; arming respects the existing `code_arm_required` setting."
        actions={
          <Button
            onClick={() => setIsAdding(true)}
            disabled={!isAdmin || isAdding}
            title={!isAdmin ? 'Admin role required' : undefined}
          >
            Add
          </Button>
        }
      >
        {panelsQuery.isLoading ? (
          <div className="text-sm text-muted-foreground">Loading…</div>
        ) : panelsQuery.data?.length ? (
          <div className="space-y-3">
            {panelsQuery.data.map((device) => (
              <div key={device.id} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="font-medium">{device.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {device.integrationType} • {device.kind} • {device.externalKey}
                    </div>
                    {device.lastError ? (
                      <div className="mt-1 text-xs text-destructive">{device.lastError}</div>
                    ) : null}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      disabled={!isAdmin || testMutation.isPending}
                      onClick={() => void testMutation.mutateAsync(device.id)}
                      title={!isAdmin ? 'Admin role required' : undefined}
                    >
                      Test beep
                    </Button>
                    <Button
                      variant={device.enabled ? 'secondary' : 'outline'}
                      disabled={!isAdmin || updateMutation.isPending}
                      onClick={() =>
                        void updateMutation.mutateAsync({ id: device.id, changes: { enabled: !device.enabled } })
                      }
                    >
                      {device.enabled ? 'Enabled' : 'Disabled'}
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={!isAdmin || deleteMutation.isPending}
                      onClick={() => void deleteMutation.mutateAsync(device.id)}
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {device.integrationType === 'zwavejs' && device.kind === 'ring_keypad_v2' ? (
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <div className="space-y-1">
                      <div className="text-sm font-medium">Test beep volume</div>
                      <Input
                        type="number"
                        min={1}
                        max={99}
                        value={beepVolumeDraftById[device.id] ?? String(device.beepVolume)}
                        onChange={(e) =>
                          setBeepVolumeDraftById((prev) => ({ ...prev, [device.id]: e.target.value }))
                        }
                        disabled={!isAdmin || updateMutation.isPending}
                      />
                      <div className="text-xs text-muted-foreground">1–99 (applies to keypad sounds we trigger)</div>
                    </div>

                    <Button
                      variant="secondary"
                      disabled={
                        !isAdmin ||
                        updateMutation.isPending ||
                        (() => {
                          const raw = (beepVolumeDraftById[device.id] ?? String(device.beepVolume)).trim()
                          const parsed = Number(raw)
                          return (
                            raw === '' ||
                            !Number.isFinite(parsed) ||
                            parsed < 1 ||
                            parsed > 99 ||
                            parsed === device.beepVolume
                          )
                        })()
                      }
                      onClick={() => {
                        const raw = (beepVolumeDraftById[device.id] ?? String(device.beepVolume)).trim()
                        const parsed = Number(raw)
                        if (!Number.isFinite(parsed)) return
                        void updateMutation
                          .mutateAsync({ id: device.id, changes: { beepVolume: Math.round(parsed) } })
                          .then(() => {
                            setBeepVolumeDraftById((prev) => {
                              const next = { ...prev }
                              delete next[device.id]
                              return next
                            })
                          })
                      }}
                    >
                      Save volume
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">None yet.</div>
        )}
      </SectionCard>

      {isAdding ? (
        <SectionCard title="Add control panel" description="Select a panel type to configure it.">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <div className="text-sm font-medium">Type</div>
              <Select
                value={panelType}
                onChange={(e) => setPanelType(e.target.value as PanelType)}
                disabled={!isAdmin || createMutation.isPending}
              >
                {PANEL_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
              {!canAddZwave ? (
                <div className="text-xs text-muted-foreground">
                  Enable Z-Wave JS in `Settings → Z-Wave JS` before adding Z-Wave control panels.
                </div>
              ) : null}
            </div>

            <div className="space-y-1">
              <div className="text-sm font-medium">Name</div>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!isAdmin || createMutation.isPending}
              />
            </div>

            {panelType === 'ring_keypad_v2_zwavejs' ? (
              <>
                <div className="space-y-1 md:col-span-2">
                  <div className="text-sm font-medium">Pick node (optional)</div>
                  <Select
                    value={selectedNodeId}
                    onChange={(e) => {
                      const next = e.target.value
                      setSelectedNodeId(next)
                      if (next) setNodeId(next)
                    }}
                    disabled={!isAdmin || createMutation.isPending || !canAddZwave}
                  >
                    <option value="">
                      {nodesQuery.isLoading ? 'Loading nodes…' : 'Select a node'}
                    </option>
                    {nodesForPicker.nodes.map((n) => (
                      <option
                        key={n.nodeId}
                        value={String(n.nodeId)}
                        disabled={
                          inferredHomeIdForFiltering != null &&
                          existingZwaveExternalKeys.has(`zwavejs:${inferredHomeIdForFiltering}:${n.nodeId}`)
                        }
                      >
                        {n.nodeId} • {n.name}
                        {n.manufacturer ? ` • ${n.manufacturer}` : ''}
                        {n.productLabel ? ` • ${n.productLabel}` : ''}
                        {inferredHomeIdForFiltering != null &&
                        existingZwaveExternalKeys.has(`zwavejs:${inferredHomeIdForFiltering}:${n.nodeId}`)
                          ? ` • already added`
                          : ''}
                      </option>
                    ))}
                  </Select>
                  <label className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Checkbox
                      checked={showAllZwaveNodes}
                      onChange={(e) => setShowAllZwaveNodes(e.target.checked)}
                      disabled={!isAdmin || createMutation.isPending || !canAddZwave}
                    />
                    Show all Z-Wave nodes
                  </label>
                  <div className="text-xs text-muted-foreground">
                    {nodesForPicker.isFiltered
                      ? nodesForPicker.filterMatchedAny
                        ? 'Showing nodes that look like keypads; toggle to show all.'
                        : 'No keypad-like nodes detected; showing all nodes. You can also type the node id manually.'
                      : 'Node list requires Z-Wave JS connectivity; you can also type the node id manually.'}
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="text-sm font-medium">Z-Wave home_id</div>
                  <Input
                    value={homeId}
                    onChange={(e) => setHomeId(e.target.value)}
                    placeholder={defaultHomeId ? String(defaultHomeId) : 'e.g. 4170970308'}
                    disabled={!isAdmin || createMutation.isPending || !canAddZwave}
                  />
                  <div className="text-xs text-muted-foreground">
                    Tip: this comes from `/api/alarm/zwavejs/status/` as `home_id`.
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="text-sm font-medium">Node ID</div>
                  <Input
                    value={nodeId}
                    onChange={(e) => setNodeId(e.target.value)}
                    placeholder="e.g. 12"
                    disabled={!isAdmin || createMutation.isPending || !canAddZwave}
                  />
                  {duplicatePanel ? (
                    <div className="text-xs text-destructive">
                      This node is already assigned to control panel “{duplicatePanel.name}” (id {duplicatePanel.id}).
                    </div>
                  ) : inferredHomeIdForFiltering == null && existingZwaveExternalKeys.size > 0 ? (
                    <div className="text-xs text-muted-foreground">
                      Enter a valid `home_id` above to enable “already added” detection.
                    </div>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>

          <div className="mt-4 flex gap-2">
            <Button
              onClick={() => void createPanel()}
              disabled={
                !isAdmin ||
                createMutation.isPending ||
                !canSubmit ||
                (panelType === 'ring_keypad_v2_zwavejs' && !canAddZwave)
              }
            >
              Add panel
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setIsAdding(false)
                resetForm()
              }}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
          </div>
        </SectionCard>
      ) : null}
    </Page>
  )
}

export default ControlPanelsPage
