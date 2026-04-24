import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SettingsTabShell } from './SettingsTabShell'

describe('SettingsTabShell', () => {
  it('imports', async () => {
    const mod = await import('./SettingsTabShell')
    expect(mod).toBeTruthy()
  })

  it('AC-12: noticeVariant="success" renders the notice with success styling; default preserves info', () => {
    const { rerender } = render(
      <SettingsTabShell isAdmin={true} notice="All good" noticeVariant="success">
        <div>child</div>
      </SettingsTabShell>
    )
    const successAlert = screen.getByText('All good').closest('[role="alert"]')
    expect(successAlert).not.toBeNull()
    expect(successAlert!.className).toMatch(/success/)

    rerender(
      <SettingsTabShell isAdmin={true} notice="All good">
        <div>child</div>
      </SettingsTabShell>
    )
    const defaultAlert = screen.getByText('All good').closest('[role="alert"]')
    expect(defaultAlert).not.toBeNull()
    expect(defaultAlert!.className).not.toMatch(/bg-success/)
  })
})
