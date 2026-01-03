import { Link } from 'react-router-dom'
import { Check, Shield } from 'lucide-react'
import { Routes } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Page } from '@/components/layout'
import { LoadingInline } from '@/components/ui/loading-inline'
import { LoadMore } from '@/components/ui/load-more'
import { SectionCard } from '@/components/ui/section-card'
import { EmptyState } from '@/components/ui/empty-state'
import { EntityImportToolbar } from '@/features/sensors/components/EntityImportToolbar'
import { EntityImportRow } from '@/features/sensors/components/EntityImportRow'
import { ImportSubmitBar } from '@/features/sensors/components/ImportSubmitBar'
import { useImportSensorsModel } from '@/features/sensors/hooks/useImportSensorsModel'

export function ImportSensorsPage() {
  const entrySensorHelp =
    'Entry sensors start the entry delay (Pending) when triggered while the alarm is armed. Turn off for instant trigger.'
  const entrySensorSuggestedHelp =
    'Suggested based on the Home Assistant device class (door/window/garage_door).'

  const model = useImportSensorsModel()

  return (
    <Page
      title="Import Sensors"
      description={
        <>
          Add Home Assistant <code>sensor</code> and <code>binary_sensor</code> entities to your alarm system.
        </>
      }
      actions={
        <Button asChild variant="outline">
          <Link to={Routes.HOME}>
            <Shield />
            Back to Home
          </Link>
        </Button>
      }
    >

      <SectionCard title="Search" description="Select which entities to import." contentClassName="flex flex-col gap-3">
        <EntityImportToolbar
          query={model.query}
          onQueryChange={model.setQuery}
          viewMode={model.viewMode}
          onViewModeChange={model.setViewMode}
          availableCount={model.availableCount}
          importedCount={model.importedCount}
          allCount={model.allCount}
        />
      </SectionCard>

      {model.success && (
        <Alert variant="success" layout="banner">
          <AlertDescription>
            <div className="flex items-center gap-2">
              <Check className="h-4 w-4" />
              Imported {model.success.count} sensor{model.success.count === 1 ? '' : 's'}.
            </div>
            {model.success.names.length > 0 && (
              <div className="mt-1 text-xs opacity-90">
                Examples: {model.success.names.join(', ')}
                {model.success.count > model.success.names.length ? '…' : ''}
              </div>
            )}
          </AlertDescription>
        </Alert>
      )}

      {model.bannerError && (
        <Alert variant="error" layout="banner">
          <AlertDescription>{model.bannerError}</AlertDescription>
        </Alert>
      )}

      <SectionCard
        title="Entities"
        description="Select the sensors you want the alarm to react to. “Entry sensor” means it starts the entry delay (Pending) instead of triggering instantly."
      >
          {model.isLoading ? (
            <LoadingInline label="Loading…" />
          ) : model.filteredCount === 0 ? (
            <EmptyState title="No entities found." description="Try a different search query or view mode." />
          ) : (
            <div className="space-y-2">
              {model.visible.map((entity) => {
                const row = model.getRowModel(entity)

                return (
                  <EntityImportRow
                    key={entity.entityId}
                    entityId={entity.entityId}
                    name={entity.name}
                    deviceClass={entity.deviceClass}
                    state={entity.state}
                    alreadyImported={row.alreadyImported}
                    importedSensorId={row.importedSensorId}
                    checked={row.checked}
                    onCheckedChange={(nextChecked) => model.setEntityChecked(entity, nextChecked)}
                    nameOverride={row.nameOverride}
                    onNameOverrideChange={(next) => model.setEntityNameOverride(entity.entityId, next)}
                    suggestedEntry={row.suggestedEntry}
                    entry={row.entry}
                    onEntryChange={(next) => model.setEntityEntry(entity.entityId, next)}
                    entryHelpOpen={row.entryHelpOpen}
                    onToggleEntryHelp={() => model.toggleEntryHelp(entity.entityId)}
                    entrySensorHelp={entrySensorHelp}
                    entrySensorSuggestedHelp={entrySensorSuggestedHelp}
                  />
                )
              })}

              {model.canLoadMore && (
                <LoadMore onClick={model.loadMore} />
              )}
            </div>
          )}
      </SectionCard>

      <ImportSubmitBar
        selectedCount={model.selectedCount}
        isSubmitting={model.isSubmitting}
        progress={model.submitProgress}
        onSubmit={model.submit}
      />
    </Page>
  )
}

export default ImportSensorsPage
