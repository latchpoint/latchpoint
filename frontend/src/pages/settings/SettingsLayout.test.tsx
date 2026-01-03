import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { SettingsLayout } from '@/pages/settings/SettingsLayout'

describe('SettingsLayout', () => {
  it('renders tabs and outlet content', () => {
    render(
      <MemoryRouter initialEntries={['/settings/alarm']}>
        <Routes>
          <Route path="/settings" element={<SettingsLayout />}>
            <Route path="alarm" element={<div>Alarm Tab</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText(/settings/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /alarm/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /mqtt/i })).toBeInTheDocument()
    expect(screen.getByText('Alarm Tab')).toBeInTheDocument()
  })
})
