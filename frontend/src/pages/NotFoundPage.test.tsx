import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import NotFoundPage from '@/pages/NotFoundPage'

describe('NotFoundPage', () => {
  it('renders 404 and a link home', () => {
    renderWithProviders(<NotFoundPage />)

    expect(screen.getByText('404')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /go home/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/')
  })
})

