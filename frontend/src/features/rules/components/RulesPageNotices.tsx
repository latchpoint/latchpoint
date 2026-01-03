import { Alert, AlertDescription } from '@/components/ui/alert'

type Props = {
  notice: string | null
  error: string | null
}

export function RulesPageNotices({ notice, error }: Props) {
  return (
    <>
      {notice ? (
        <Alert variant="info" layout="banner">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}
      {error ? (
        <Alert variant="error" layout="banner">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}

