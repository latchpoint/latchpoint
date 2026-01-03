import { Button } from '@/components/ui/button'

export interface LoadMoreProps {
  onClick: () => void
  label?: string
}

export function LoadMore({ onClick, label = 'Load more' }: LoadMoreProps) {
  return (
    <div className="pt-2">
      <Button type="button" variant="outline" onClick={onClick}>
        {label}
      </Button>
    </div>
  )
}
