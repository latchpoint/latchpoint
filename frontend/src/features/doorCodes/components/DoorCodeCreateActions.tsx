import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ReauthPasswordField } from '@/features/codes/components/ReauthPasswordField'

type Props = {
  reauthPassword: string
  onReauthPasswordChange: (next: string) => void
  error: string | null
  onSubmit: () => void
  isBusy: boolean
}

export function DoorCodeCreateActions({ reauthPassword, onReauthPasswordChange, error, onSubmit, isBusy }: Props) {
  return (
    <>
      <ReauthPasswordField
        id="door-code-create-password"
        value={reauthPassword}
        onChange={onReauthPasswordChange}
        disabled={isBusy}
        helpTip="Required to create a door code."
        required
      />

      {error ? (
        <Alert variant="error" layout="inline">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex items-center justify-end">
        <Button onClick={onSubmit} disabled={isBusy}>
          {isBusy ? 'Creating…' : 'Create Door Code'}
        </Button>
      </div>
    </>
  )
}

