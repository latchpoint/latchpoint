import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

type Props = {
  description: string
  layout?: 'inline' | 'banner'
}

export function AdminActionRequiredAlert({ description, layout = 'inline' }: Props) {
  return (
    <Alert variant="warning" layout={layout}>
      <AlertTitle>Admin action required</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
    </Alert>
  )
}
