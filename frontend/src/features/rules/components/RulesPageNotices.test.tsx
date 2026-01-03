import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RulesPageNotices } from '@/features/rules/components/RulesPageNotices'

describe('RulesPageNotices', () => {
  it('renders notice and error banners', () => {
    render(<RulesPageNotices notice="Notice" error="Error" />)
    expect(screen.getByText('Notice')).toBeInTheDocument()
    expect(screen.getByText('Error')).toBeInTheDocument()
  })
})

