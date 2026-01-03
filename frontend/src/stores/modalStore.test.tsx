import React from 'react'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useModalStore, useModal } from '@/stores'

describe('modalStore', () => {
  beforeEach(() => {
    useModalStore.setState({ modal: null })
  })

  it('opens and closes modals via store', () => {
    const store = useModalStore.getState()

    expect(store.modal).toBeNull()
    expect(store.isOpen('confirm-action')).toBe(false)

    store.openModal('confirm-action', {
      title: 'Confirm',
      message: 'Are you sure?',
      onConfirm: () => {},
    })

    expect(useModalStore.getState().isOpen('confirm-action')).toBe(true)

    store.closeModal()
    expect(useModalStore.getState().modal).toBeNull()
  })

  it('provides type-safe open/close via useModal hook', () => {
    const { result } = renderHook(() => useModal('code-entry'))

    act(() => {
      result.current.open({
        title: 'Enter Code',
        onSubmit: () => {},
      })
    })

    expect(result.current.isOpen).toBe(true)
    expect(result.current.data?.title).toBe('Enter Code')

    act(() => {
      result.current.close()
    })

    expect(useModalStore.getState().modal).toBeNull()
  })
})

