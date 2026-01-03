import { cn } from '@/lib/utils'
import { Button, type ButtonProps } from '@/components/ui/button'

export interface IconButtonProps extends Omit<ButtonProps, 'size'> {
  'aria-label': string
}

export function IconButton({ className, variant = 'ghost', ...props }: IconButtonProps) {
  return <Button size="icon" variant={variant} className={cn(className)} {...props} />
}
