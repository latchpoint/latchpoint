import { useState } from 'react'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { AlarmState, UserRole } from '@/lib/constants'
import type { AlarmStateType, UserRoleType } from '@/lib/constants'
import { getErrorMessage } from '@/types/errors'
import type { User } from '@/types'
import { useCodesQuery, useCreateCodeMutation, useUpdateCodeMutation, useUsersQuery } from '@/hooks/useCodesQueries'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Page } from '@/components/layout'
import { SectionCard } from '@/components/ui/section-card'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingInline } from '@/components/ui/loading-inline'
import { CodeCard } from '@/features/codes/components/CodeCard'
import { CodeCreateCard } from '@/features/codes/components/CodeCreateCard'
import { CodesOwnerSelector } from '@/features/codes/components/CodesOwnerSelector'

const ARMABLE_STATES: AlarmStateType[] = [
  AlarmState.ARMED_HOME,
  AlarmState.ARMED_AWAY,
  AlarmState.ARMED_NIGHT,
  AlarmState.ARMED_VACATION,
  AlarmState.ARMED_CUSTOM_BYPASS,
]

function isAdminRole(role: UserRoleType | undefined): boolean {
  return role === UserRole.ADMIN
}

export function CodesPage() {
  return <CodesPageContent />
}

function CodesPageContent() {
  const currentUserQuery = useCurrentUserQuery()
  const user = currentUserQuery.data ?? null
  const isAdmin = isAdminRole(user?.role)

  const [selectedUserId, setSelectedUserId] = useState<string>('')
  const [editingCodeId, setEditingCodeId] = useState<number | null>(null)

  const usersQuery = useUsersQuery(isAdmin)
  const usersForSelect: User[] = usersQuery.data || []

  const selectedUserIdOrDefault = selectedUserId || user?.id || ''
  const targetUserId = isAdmin ? selectedUserIdOrDefault : user?.id || ''

  const codesQuery = useCodesQuery({ userId: targetUserId, isAdmin })
  const createMutation = useCreateCodeMutation(targetUserId)
  const updateMutation = useUpdateCodeMutation(targetUserId)

  const selectedUserDisplay = (() => {
    if (!isAdmin) return user?.displayName || ''
    const selected = usersForSelect.find((u) => u.id === targetUserId)
    return selected?.displayName || selected?.email || ''
  })()

  return (
    <Page title="Alarm Codes">
      {isAdmin && (
        <SectionCard title="Manage User Codes" contentClassName="space-y-4">
          <CodesOwnerSelector
            users={usersForSelect}
            value={selectedUserIdOrDefault}
            onChange={setSelectedUserId}
            isLoading={usersQuery.isLoading}
            error={usersQuery.isError ? usersQuery.error : null}
          />

          <CodeCreateCard
            userId={targetUserId}
            armableStates={ARMABLE_STATES}
            isPending={createMutation.isPending}
            onCreate={(req) => createMutation.mutateAsync(req)}
          />
        </SectionCard>
      )}

      {!isAdmin && <SectionCard title="Your Codes" description="Ask an admin to create or update codes for your account." />}

      <SectionCard
        title={
          <>
            Codes {selectedUserDisplay ? <span className="text-muted-foreground">({selectedUserDisplay})</span> : null}
          </>
        }
        contentClassName="space-y-4"
      >
        {codesQuery.isLoading && <LoadingInline label="Loading codes…" />}
        {codesQuery.isError && (
          <Alert variant="error" layout="inline">
            <AlertDescription>Failed to load codes: {getErrorMessage(codesQuery.error) || 'Unknown error'}</AlertDescription>
          </Alert>
        )}
        {!codesQuery.isLoading && !codesQuery.isError && (codesQuery.data || []).length === 0 && (
          <EmptyState title="No codes found." description="Create a code above or ask an admin to add one." />
        )}

        {(codesQuery.data || []).map((code) => (
          <CodeCard
            key={code.id}
            code={code}
            armableStates={ARMABLE_STATES}
            canManage={isAdmin}
            isEditing={editingCodeId === code.id}
            isPending={updateMutation.isPending}
            onBeginEdit={() => setEditingCodeId(code.id)}
            onCancelEdit={() => setEditingCodeId(null)}
            onUpdate={(id, req) => updateMutation.mutateAsync({ id, req })}
          />
        ))}
      </SectionCard>
    </Page>
  )
}

export default CodesPage

