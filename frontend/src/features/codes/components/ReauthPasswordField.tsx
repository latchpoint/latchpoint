import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'

type Props = {
  id: string
  label?: string
  value: string
  onChange: (next: string) => void
  disabled?: boolean
  placeholder?: string
  helpTip?: string | null
  required?: boolean
}

export function ReauthPasswordField({
  id,
  label = 'Re-authenticate (password)',
  value,
  onChange,
  disabled,
  placeholder = 'Your account password',
  helpTip = 'Required to save changes. This prevents someone with an unlocked session from changing secrets silently.',
  required,
}: Props) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium" htmlFor={id}>
          {label}
          {required ? <span className="text-destructive"> *</span> : null}
        </label>
        {helpTip ? <HelpTip content={helpTip} /> : null}
      </div>
      <Input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
    </div>
  )
}
