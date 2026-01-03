import type { AlarmStateType } from '@/lib/constants'
import type { CreateCodeRequest } from '@/types'
import { isCreateCodeTypeOption } from '@/lib/typeGuards'
import { getSelectValue } from '@/lib/formHelpers'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { AllowedArmStatesPicker } from '@/features/codes/components/AllowedArmStatesPicker'
import { ReauthPasswordField } from '@/features/codes/components/ReauthPasswordField'
import { CodeTemporaryRestrictionsFields } from '@/features/codes/components/CodeTemporaryRestrictionsFields'
import { useCodeCreateModel } from '@/features/codes/hooks/useCodeCreateModel'

type Props = {
  userId: string
  armableStates: AlarmStateType[]
  isPending: boolean
  onCreate: (req: CreateCodeRequest) => Promise<unknown>
}

export function CodeCreateCard({ userId, armableStates, isPending, onCreate }: Props) {
  const model = useCodeCreateModel({ userId, armableStates, onCreate })

  return (
    <div className="rounded-md border border-input p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="font-medium">Create Code</div>
          <div className="text-sm text-muted-foreground">Codes are secrets; they can’t be viewed after creation.</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <FormField
          label="Type"
          htmlFor="create-type"
          help="Temporary codes can have date/time and day-of-week restrictions. Permanent codes are always valid (unless deactivated)."
        >
          <Select
            id="create-type"
            value={model.codeType}
            onChange={(e) => model.setCodeType(getSelectValue(e, isCreateCodeTypeOption, 'permanent'))}
            disabled={isPending}
          >
            <option value="permanent">Permanent</option>
            <option value="temporary">Temporary</option>
          </Select>
        </FormField>

        <FormField label="Label (optional)" htmlFor="create-label">
          <Input
            id="create-label"
            value={model.label}
            onChange={(e) => model.setLabel(e.target.value)}
            placeholder="Front door"
            disabled={isPending}
          />
        </FormField>

        <FormField
          label="Code (4–8 digits)"
          htmlFor="create-code"
          help="Codes are stored hashed on the server. Enter a 4–8 digit PIN; you cannot view it later."
          description="Codes are never shown again after creation."
        >
          <Input
            id="create-code"
            value={model.code}
            onChange={(e) => model.setCode(e.target.value)}
            placeholder="••••"
            inputMode="numeric"
            autoComplete="one-time-code"
            disabled={isPending}
          />
        </FormField>
      </div>

      {model.isTemporary ? (
        <CodeTemporaryRestrictionsFields
          disabled={isPending}
          startAtLocal={model.startAtLocal}
          endAtLocal={model.endAtLocal}
          onActiveWindowChange={(next) => {
            model.setStartAtLocal(next.start)
            model.setEndAtLocal(next.end)
          }}
          days={model.days}
          onDaysChange={model.setDays}
          windowStart={model.windowStart}
          windowEnd={model.windowEnd}
          onWindowStartChange={model.setWindowStart}
          onWindowEndChange={model.setWindowEnd}
        />
      ) : null}

      <div className="mt-4 space-y-2">
        <AllowedArmStatesPicker
          states={armableStates}
          value={model.allowedStates}
          onChange={model.setAllowedStates}
          disabled={isPending}
          helpTip="Controls which armed states this code is allowed to arm into."
        />
      </div>

      <div className="mt-4 space-y-2">
        <ReauthPasswordField
          id="create-password"
          value={model.reauthPassword}
          onChange={model.setReauthPassword}
          disabled={isPending}
          helpTip="Required to create or modify codes. This prevents someone with an unlocked session from changing codes silently."
        />
      </div>

      {model.error && (
        <Alert variant="error" layout="inline" className="mt-4">
          <AlertDescription>{model.error}</AlertDescription>
        </Alert>
      )}

      <div className="mt-4 flex items-center justify-end">
        <Button onClick={() => void model.submit()} disabled={isPending}>
          {isPending ? 'Creating…' : 'Create Code'}
        </Button>
      </div>
    </div>
  )
}
