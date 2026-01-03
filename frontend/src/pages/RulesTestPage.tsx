import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Page } from '@/components/layout'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { HelpTip } from '@/components/ui/help-tip'
import { createScenarioRow } from '@/features/rulesTest/scenarios'
import { ScenarioRowsEditor } from '@/features/rulesTest/components/ScenarioRowsEditor'
import { RulesTestHeaderActions } from '@/features/rulesTest/components/RulesTestHeaderActions'
import { RulesTestModeToggle } from '@/features/rulesTest/components/RulesTestModeToggle'
import { DeltaChangeControls } from '@/features/rulesTest/components/DeltaChangeControls'
import { SimulationOptionsBar } from '@/features/rulesTest/components/SimulationOptionsBar'
import { SavedScenariosCard } from '@/features/rulesTest/components/SavedScenariosCard'
import { RulesTestResults } from '@/features/rulesTest/components/RulesTestResults'
import { Button } from '@/components/ui/button'
import { useRulesTestPageModel } from '@/features/rulesTest/hooks/useRulesTestPageModel'

export function RulesTestPage() {
  const model = useRulesTestPageModel()

  return (
    <Page
      title="Test Rules"
      description="Simulate entity states and see which rules would match (no actions executed)."
      actions={
        <RulesTestHeaderActions
          onSyncHa={model.syncEntities}
          onSyncZwave={model.syncZwavejsEntities}
          onRefreshEntities={model.refreshEntities}
          disabled={model.isLoading || model.isRunning}
        />
      }
    >
      {model.displayedError ? (
        <Alert variant="error" layout="banner">
          <AlertDescription>{model.displayedError}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Scenario</CardTitle>
          <CardDescription>
            Provide a set of entity state overrides for simulation.
            <HelpTip className="ml-2" content="This page is a dry-run. It never executes alarm actions or Home Assistant services." />
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RulesTestModeToggle mode={model.mode} onModeChange={model.setMode} disabled={model.isRunning} />

          {model.mode === 'scenario' ? (
            <ScenarioRowsEditor
              rows={model.rows}
              setRows={model.setRows}
              entityIdOptions={model.entityIdOptions}
              entitiesById={model.entitiesById}
              setRowEntityId={model.setRowEntityId}
              isLoading={model.isLoading}
              isRunning={model.isRunning}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Single Change{' '}
                  <HelpTip
                    className="ml-1"
                    content="Runs baseline with no overrides (registry states), then runs again with one entity state override. The Results page shows differences in rule match status."
                  />
                </CardTitle>
                <CardDescription>
                  Runs a baseline simulation (current registry states), then applies one entity state change and shows what changes.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <DeltaChangeControls
                  entityIdOptions={model.entityIdOptions}
                  deltaEntityId={model.deltaEntityId}
                  onDeltaEntityIdChange={model.setDeltaEntityId}
                  deltaState={model.deltaState}
                  onDeltaStateChange={model.setDeltaState}
                  baselineState={
                    model.deltaEntityId.trim() && model.entitiesById.get(model.deltaEntityId.trim())?.lastState != null
                      ? String(model.entitiesById.get(model.deltaEntityId.trim())?.lastState)
                      : null
                  }
                  onRunBaselineAndChange={model.simulateDelta}
                  disabled={model.isLoading || model.isRunning}
                />
              </CardContent>
            </Card>
          )}

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => model.setRows((prev) => [...prev, createScenarioRow()])} disabled={model.isRunning}>
              Add entity
            </Button>
            <Button type="button" variant="outline" onClick={() => model.setRows([createScenarioRow()])} disabled={model.isRunning}>
              Reset
            </Button>
          </div>

          <SimulationOptionsBar
            assumeForSeconds={model.assumeForSeconds}
            onAssumeForSecondsChange={model.setAssumeForSeconds}
            alarmState={model.alarmState}
            onAlarmStateChange={model.setAlarmState}
            showRunButton={model.mode === 'scenario'}
            onRun={model.simulate}
            disabled={model.isRunning}
          />

          <SavedScenariosCard
            scenarioName={model.scenarioName}
            onScenarioNameChange={model.setScenarioName}
            onSave={model.saveScenario}
            savedScenarios={model.savedScenarios}
            selectedScenario={model.selectedScenario}
            onSelectedScenarioChange={model.setSelectedScenario}
            onLoad={model.loadScenario}
            onDelete={model.deleteScenario}
            disabled={model.isRunning}
          />
        </CardContent>
      </Card>

      <RulesTestResults mode={model.mode} result={model.result} baselineResult={model.baselineResult} />
    </Page>
  )
}

export default RulesTestPage
