import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { EntityImportRow } from '@/features/sensors/components/EntityImportRow'

describe('EntityImportRow', () => {
  it('shows details and blocks checkbox when already imported', () => {
    renderWithProviders(
      <EntityImportRow
        entityId="binary_sensor.motion"
        name="Motion"
        deviceClass="motion"
        state="off"
        alreadyImported={true}
        importedSensorId={12}
        checked={false}
        onCheckedChange={() => {}}
        nameOverride="Motion"
        onNameOverrideChange={() => {}}
        suggestedEntry={false}
        entry={false}
        onEntryChange={() => {}}
        entryHelpOpen={false}
        onToggleEntryHelp={() => {}}
        entrySensorHelp="help"
        entrySensorSuggestedHelp="suggested"
      />
    )

    expect(screen.getByText(/already imported/i)).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeDisabled()
  })

  it('allows selecting and editing name/entry with help', async () => {
    const user = userEvent.setup()
    const onCheckedChange = vi.fn()
    const onNameOverrideChange = vi.fn()
    const onEntryChange = vi.fn()
    const onToggleEntryHelp = vi.fn()

    const { rerender } = renderWithProviders(
      <EntityImportRow
        entityId="binary_sensor.front_door"
        name="Front Door"
        deviceClass="door"
        state="on"
        alreadyImported={false}
        importedSensorId={null}
        checked={false}
        onCheckedChange={onCheckedChange}
        nameOverride="Front Door"
        onNameOverrideChange={onNameOverrideChange}
        suggestedEntry={true}
        entry={true}
        onEntryChange={onEntryChange}
        entryHelpOpen={false}
        onToggleEntryHelp={onToggleEntryHelp}
        entrySensorHelp="entry help"
        entrySensorSuggestedHelp="suggested help"
      />
    )

    await user.click(screen.getByRole('checkbox'))
    expect(onCheckedChange).toHaveBeenCalledWith(true)

    rerender(
      <EntityImportRow
        entityId="binary_sensor.front_door"
        name="Front Door"
        deviceClass="door"
        state="on"
        alreadyImported={false}
        importedSensorId={null}
        checked={true}
        onCheckedChange={onCheckedChange}
        nameOverride="Front Door"
        onNameOverrideChange={onNameOverrideChange}
        suggestedEntry={true}
        entry={true}
        onEntryChange={onEntryChange}
        entryHelpOpen={false}
        onToggleEntryHelp={onToggleEntryHelp}
        entrySensorHelp="entry help"
        entrySensorSuggestedHelp="suggested help"
      />
    )

    await user.type(screen.getByDisplayValue('Front Door'), ' X')
    expect(onNameOverrideChange).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /help/i }))
    expect(onToggleEntryHelp).toHaveBeenCalled()
  })
})

