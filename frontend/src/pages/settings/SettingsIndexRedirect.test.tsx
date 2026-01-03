import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { SettingsIndexRedirect } from '@/pages/settings/SettingsIndexRedirect'

describe('SettingsIndexRedirect', () => {
  it('redirects to alarm', () => {
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Routes>
          <Route path="/settings" element={<SettingsIndexRedirect />} />
          <Route path="/settings/alarm" element={<div>Alarm</div>} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Alarm')).toBeInTheDocument()
  })
})
