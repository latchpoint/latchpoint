import * as React from 'react'

import { Input } from '@/components/ui/input'

export interface DatalistInputProps extends React.ComponentProps<typeof Input> {
  listId: string
  options: string[]
  maxOptions?: number
}

export function DatalistInput({ listId, options, maxOptions = 400, ...props }: DatalistInputProps) {
  return (
    <>
      <datalist id={listId}>
        {options.slice(0, maxOptions).map((value) => (
          <option key={value} value={value} />
        ))}
      </datalist>
      <Input list={listId} {...props} />
    </>
  )
}

