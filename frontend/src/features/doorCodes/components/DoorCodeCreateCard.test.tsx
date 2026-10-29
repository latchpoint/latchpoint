import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import type { DoorCodeCreateForm } from './DoorCodeCreateForm'
import { DoorCodeCreateCard } from './DoorCodeCreateCard'

// The date range picker is a calendar popover, so the form is stubbed with
// buttons that fill it in and submit.
vi.mock('./DoorCodeCreateForm', () => ({
  DoorCodeCreateForm: (props: ComponentProps<typeof DoorCodeCreateForm>) => (
    <div>
      <button
        type="button"
        onClick={() => {
          props.onCodeTypeChange('temporary')
          props.onCodeChange('1357')
          props.onReauthPasswordChange('pw')
          props.lockPicker.onSelectedChange(new Set(['lock.front_door']))
        }}
      >
        fill
      </button>
      <button type="button" onClick={() => props.onActiveWindowChange({ start: '', end: '2020-01-01T10:00' })}>
        past end
      </button>
      <button type="button" onClick={() => props.onActiveWindowChange({ start: '', end: '2999-01-01T10:00' })}>
        future end
      </button>
      <button type="button" onClick={props.onSubmit}>
        submit
      </button>
      {props.error ? <div role="alert">{props.error}</div> : null}
    </div>
  ),
}))

function renderCard(onCreate = vi.fn().mockResolvedValue(undefined)) {
  renderWithProviders(
    <DoorCodeCreateCard
      userId="user-1"
      locks={[]}
      locksIsLoading={false}
      locksError={null}
      syncHa={{ onClick: vi.fn(), isPending: false }}
      syncZwave={{ onClick: vi.fn(), isPending: false }}
      isPending={false}
      onCreate={onCreate}
    />,
  )
  return onCreate
}

describe('DoorCodeCreateCard', () => {
  it('refuses an end date in the past without calling the API (#145)', () => {
    const onCreate = renderCard()

    fireEvent.click(screen.getByRole('button', { name: 'fill' }))
    fireEvent.click(screen.getByRole('button', { name: 'past end' }))
    fireEvent.click(screen.getByRole('button', { name: 'submit' }))

    expect(screen.getByRole('alert')).toHaveTextContent('The active window must end in the future.')
    expect(onCreate).not.toHaveBeenCalled()
  })

  it('creates a code whose end date is in the future', () => {
    const onCreate = renderCard()

    fireEvent.click(screen.getByRole('button', { name: 'fill' }))
    fireEvent.click(screen.getByRole('button', { name: 'future end' }))
    fireEvent.click(screen.getByRole('button', { name: 'submit' }))

    expect(screen.queryByRole('alert')).toBeNull()
    expect(onCreate).toHaveBeenCalledTimes(1)
    expect(onCreate.mock.calls[0][0]).toMatchObject({
      codeType: 'temporary',
      endAt: new Date('2999-01-01T10:00').toISOString(),
      maxUses: null,
    })
  })
})
