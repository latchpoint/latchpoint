import { Pill } from '@/components/ui/pill'
import type { PillProps } from '@/components/ui/pill'

type Props = {
  value: boolean
  trueLabel: string
  falseLabel: string
  trueVariant?: PillProps['variant']
  falseVariant?: PillProps['variant']
  trueClassName?: string
  falseClassName?: string
}

export function BooleanStatusPill({
  value,
  trueLabel,
  falseLabel,
  trueVariant = 'default',
  falseVariant = 'muted',
  trueClassName,
  falseClassName,
}: Props) {
  return (
    <Pill variant={value ? trueVariant : falseVariant} className={value ? trueClassName : falseClassName}>
      {value ? trueLabel : falseLabel}
    </Pill>
  )
}

