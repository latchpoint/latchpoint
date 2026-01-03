import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { CodeCard } from '@/features/codes/components/CodeCard'
import type { AlarmCode } from '@/types'
import { AlarmState } from '@/lib/constants'

vi.mock('@/features/codes/components/CodeEditPanel', () => {
  return {
    CodeEditPanel: () => <div>CodeEditPanel</div>,
  }
})

function makeCode(overrides?: Partial<AlarmCode>): AlarmCode {
  return {
    id: 1,
    userId: 'u1',
    userDisplayName: 'Alice',
    label: 'Front door',
    codeType: 'permanent',
    pinLength: 4,
    isActive: true,
    maxUses: null,
    usesCount: 0,
    startAt: null,
    endAt: null,
    daysOfWeek: null,
    windowStart: null,
    windowEnd: null,
    allowedStates: [AlarmState.ARMED_HOME],
    lastUsedAt: null,
    createdAt: '2025-01-01T00:00:00Z',
    updatedAt: '2025-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('CodeCard', () => {
  it('shows edit button when manageable and calls onBeginEdit', async () => {
    const user = userEvent.setup()
    const onBeginEdit = vi.fn()

    renderWithProviders(
      <CodeCard
        code={makeCode()}
        armableStates={[AlarmState.ARMED_HOME]}
        canManage={true}
        isEditing={false}
        isPending={false}
        onBeginEdit={onBeginEdit}
        onCancelEdit={() => {}}
        onUpdate={() => Promise.resolve()}
      />
    )

    await user.click(screen.getByRole('button', { name: /edit/i }))
    expect(onBeginEdit).toHaveBeenCalledTimes(1)
  })

  it('does not show edit controls when canManage is false', () => {
    renderWithProviders(
      <CodeCard
        code={makeCode()}
        armableStates={[AlarmState.ARMED_HOME]}
        canManage={false}
        isEditing={false}
        isPending={false}
        onBeginEdit={() => {}}
        onCancelEdit={() => {}}
        onUpdate={() => Promise.resolve()}
      />
    )

    expect(screen.queryByRole('button', { name: /edit/i })).toBeNull()
  })

  it('renders edit panel when editing', () => {
    renderWithProviders(
      <CodeCard
        code={makeCode()}
        armableStates={[AlarmState.ARMED_HOME]}
        canManage={true}
        isEditing={true}
        isPending={false}
        onBeginEdit={() => {}}
        onCancelEdit={() => {}}
        onUpdate={() => Promise.resolve()}
      />
    )

    expect(screen.getByText('CodeEditPanel')).toBeInTheDocument()
  })
})

