import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom'
import { DebugLayout } from '@/pages/debug/DebugLayout'

describe('DebugLayout', () => {
  it('renders tabs and outlet content', () => {
    render(
      <MemoryRouter initialEntries={['/debug/entities']}>
        <Routes>
          <Route path="/debug" element={<DebugLayout />}>
            <Route path="entities" element={<div>Entities Content</div>} />
            <Route path="logs" element={<div>Logs Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: /entities/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /logs/i })).toBeInTheDocument()
    expect(screen.getByText('Entities Content')).toBeInTheDocument()
  })

  it('DebugIndexRedirect redirects to entities', () => {
    render(
      <MemoryRouter initialEntries={['/debug']}>
        <Routes>
          <Route path="/debug" element={<DebugLayout />}>
            <Route index element={<Navigate to="entities" replace />} />
            <Route path="entities" element={<div>Entities Content</div>} />
            <Route path="logs" element={<div>Logs Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Entities Content')).toBeInTheDocument()
  })
})
