import { useMemo, useState } from 'react'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useUsersQuery } from '@/hooks/useCodesQueries'
import { useEntitiesQuery, useSyncEntitiesMutation } from '@/hooks/useRulesQueries'
import { useSyncZwavejsEntitiesMutation } from '@/hooks/useZwavejs'
import {
  useCreateDoorCodeMutation,
  useDeleteDoorCodeMutation,
  useDoorCodesQuery,
  useUpdateDoorCodeMutation,
} from '@/hooks/useDoorCodesQueries'
import { UserRole } from '@/lib/constants'
import { getErrorMessage } from '@/types/errors'
import type { Entity, User } from '@/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingInline } from '@/components/ui/loading-inline'
import { Page } from '@/components/layout'
import { SectionCard } from '@/components/ui/section-card'
import { DoorCodeCard } from '@/features/doorCodes/components/DoorCodeCard'
import { DoorCodeCreateCard } from '@/features/doorCodes/components/DoorCodeCreateCard'
import { DoorCodesOwnerSelector } from '@/features/doorCodes/components/DoorCodesOwnerSelector'
import { LockConfigSyncCard } from '@/features/doorCodes/components/LockConfigSyncCard'

function isAdminRole(role: string | undefined): boolean {
  return role === UserRole.ADMIN
}

export function DoorCodesPage() {
  const currentUserQuery = useCurrentUserQuery()
  const user = currentUserQuery.data ?? null
  const isAdmin = isAdminRole(user?.role)

  const [selectedUserId, setSelectedUserId] = useState<string>('')
  const [editingCodeId, setEditingCodeId] = useState<number | null>(null)

  const usersQuery = useUsersQuery(isAdmin)
  const usersForSelect: User[] = usersQuery.data || []

  const selectedUserIdOrDefault = selectedUserId || user?.id || ''
  const targetUserId = isAdmin ? selectedUserIdOrDefault : user?.id || ''

  const doorCodesQuery = useDoorCodesQuery({ userId: targetUserId, isAdmin })
  const entitiesQuery = useEntitiesQuery()
  const syncEntitiesMutation = useSyncEntitiesMutation()
  const syncZwavejsEntitiesMutation = useSyncZwavejsEntitiesMutation()

  const createMutation = useCreateDoorCodeMutation(targetUserId)
  const updateMutation = useUpdateDoorCodeMutation(targetUserId)
  const deleteMutation = useDeleteDoorCodeMutation(targetUserId)

  const selectedUserDisplay = (() => {
    if (!isAdmin) return user?.displayName || ''
    const selected = usersForSelect.find((u) => u.id === targetUserId)
    return selected?.displayName || selected?.email || ''
  })()

  const lockNameByEntityId = useMemo(() => {
    const map = new Map<string, string>()
    for (const entity of entitiesQuery.data || []) {
      if (entity.domain !== 'lock') continue
      if (entity.entityId && entity.name) map.set(entity.entityId, entity.name)
    }
    return map
  }, [entitiesQuery.data])

  const lockEntities: Entity[] = useMemo(() => {
    return (entitiesQuery.data || []).filter((entity) => entity.domain === 'lock')
  }, [entitiesQuery.data])

  return (
    <Page title="Door Codes">
      {isAdmin ? (
        <>
          <SectionCard title="Manage Door Codes" contentClassName="space-y-4">
            <DoorCodesOwnerSelector
              users={usersForSelect}
              value={selectedUserIdOrDefault}
              onChange={setSelectedUserId}
              isLoading={usersQuery.isLoading}
              error={usersQuery.isError ? usersQuery.error : null}
            />

            <DoorCodeCreateCard
              userId={targetUserId}
              locks={lockEntities}
              locksIsLoading={entitiesQuery.isLoading}
              locksError={entitiesQuery.isError ? entitiesQuery.error : null}
              syncHa={{ onClick: () => syncEntitiesMutation.mutate(), isPending: syncEntitiesMutation.isPending }}
              syncZwave={{
                onClick: () => syncZwavejsEntitiesMutation.mutate(),
                isPending: syncZwavejsEntitiesMutation.isPending,
              }}
              isPending={createMutation.isPending}
              onCreate={(req) => createMutation.mutateAsync(req)}
            />
          </SectionCard>

          <SectionCard
            title="Sync Codes from Lock"
            description="Pull existing user codes and supported schedules from a Z-Wave JS lock into LatchPoint. Note: if you re-include a Z-Wave stick (factory reset or re-pair), previously synced codes will be orphaned because the lock entity ID changes. You may need to delete the old synced codes and re-sync."
            contentClassName="space-y-4"
          >
            <LockConfigSyncCard
              userId={targetUserId}
              locks={lockEntities}
              locksIsLoading={entitiesQuery.isLoading}
              locksError={entitiesQuery.isError ? entitiesQuery.error : null}
            />
          </SectionCard>
        </>
      ) : (
        <SectionCard title="Your Door Codes" description="Ask an admin to create or update door codes for your account." />
      )}

      <SectionCard
        title={
          <>
            Door Codes {selectedUserDisplay ? <span className="text-muted-foreground">({selectedUserDisplay})</span> : null}
          </>
        }
        contentClassName="space-y-4"
      >
        {doorCodesQuery.isLoading && <LoadingInline label="Loading door codes…" />}
        {doorCodesQuery.isError && (
          <Alert variant="error" layout="inline">
            <AlertDescription>Failed to load door codes: {getErrorMessage(doorCodesQuery.error) || 'Unknown error'}</AlertDescription>
          </Alert>
        )}
        {!doorCodesQuery.isLoading && !doorCodesQuery.isError && (doorCodesQuery.data || []).length === 0 && (
          <EmptyState title="No door codes found." description="Create a door code above or ask an admin to add one." />
        )}

        {(doorCodesQuery.data || []).map((code) => (
          <DoorCodeCard
            key={code.id}
            code={code}
            canManage={isAdmin}
            isEditing={editingCodeId === code.id}
            lockNameByEntityId={lockNameByEntityId}
            locks={lockEntities}
            locksIsLoading={entitiesQuery.isLoading}
            locksError={entitiesQuery.isError ? entitiesQuery.error : null}
            isSaving={updateMutation.isPending}
            isDeleting={deleteMutation.isPending}
            onBeginEdit={() => setEditingCodeId(code.id)}
            onCloseEdit={() => setEditingCodeId(null)}
            onUpdate={(id, req) => updateMutation.mutateAsync({ id, req })}
            onDelete={(id, reauthPassword) => deleteMutation.mutateAsync({ id, reauthPassword })}
          />
        ))}
      </SectionCard>
    </Page>
  )
}

export default DoorCodesPage
