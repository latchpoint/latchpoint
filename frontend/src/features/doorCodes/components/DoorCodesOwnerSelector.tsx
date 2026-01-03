import type { User } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { FormField } from '@/components/ui/form-field'
import { Select } from '@/components/ui/select'

type Props = {
  users: User[]
  value: string
  onChange: (nextUserId: string) => void
  isLoading: boolean
  error: unknown
}

export function DoorCodesOwnerSelector({ users, value, onChange, isLoading, error }: Props) {
  const errorMessage = error ? `Failed to load users: ${getErrorMessage(error) || 'Unknown error'}` : null

  return (
    <FormField label="Owner" htmlFor="door-codes-owner" error={errorMessage} help="The user this code belongs to">
      <Select
        id="door-codes-owner"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={isLoading || !!error}
      >
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.displayName} ({u.email})
          </option>
        ))}
      </Select>
    </FormField>
  )
}
