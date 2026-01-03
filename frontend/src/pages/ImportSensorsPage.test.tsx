import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import ImportSensorsPage from '@/pages/ImportSensorsPage'

let model: any

vi.mock('@/features/sensors/hooks/useImportSensorsModel', () => {
  return {
    useImportSensorsModel: () => model,
  }
})

vi.mock('@/features/sensors/components/EntityImportToolbar', () => {
  return { EntityImportToolbar: () => <div>EntityImportToolbar</div> }
})
vi.mock('@/features/sensors/components/EntityImportRow', () => {
  return { EntityImportRow: () => <div>EntityImportRow</div> }
})
vi.mock('@/features/sensors/components/ImportSubmitBar', () => {
  return { ImportSubmitBar: () => <div>ImportSubmitBar</div> }
})

describe('ImportSensorsPage', () => {
  beforeEach(() => {
    model = {
      query: '',
      setQuery: vi.fn(),
      viewMode: 'available',
      setViewMode: vi.fn(),
      availableCount: 0,
      importedCount: 0,
      allCount: 0,
      success: null,
      bannerError: null,
      isLoading: false,
      filteredCount: 0,
      visible: [],
      getRowModel: vi.fn(),
      canLoadMore: false,
      loadMore: vi.fn(),
      selectedCount: 0,
      isSubmitting: false,
      submitProgress: null,
      submit: vi.fn(),
      setEntityChecked: vi.fn(),
      setEntityNameOverride: vi.fn(),
      setEntityEntry: vi.fn(),
      toggleEntryHelp: vi.fn(),
    }
  })

  it('renders empty state when no entities match filters', () => {
    renderWithProviders(<ImportSensorsPage />)

    expect(screen.getByText(/import sensors/i)).toBeInTheDocument()
    expect(screen.getByText('EntityImportToolbar')).toBeInTheDocument()
    expect(screen.getByText(/no entities found/i)).toBeInTheDocument()
    expect(screen.getByText('ImportSubmitBar')).toBeInTheDocument()
  })

  it('renders success banner when import succeeds', () => {
    model.success = { count: 2, names: ['Front Door', 'Garage'] }
    renderWithProviders(<ImportSensorsPage />)
    expect(screen.getByText(/imported 2 sensors/i)).toBeInTheDocument()
  })
})

