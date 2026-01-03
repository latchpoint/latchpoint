import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { DoorCodeTypeOption } from '@/features/doorCodes/components/DoorCodeCreateForm'

type Props = {
  codeType: DoorCodeTypeOption
  onCodeTypeChange: (next: DoorCodeTypeOption) => void
  label: string
  onLabelChange: (next: string) => void
  code: string
  onCodeChange: (next: string) => void
  maxUses: string
  onMaxUsesChange: (next: string) => void
  isBusy: boolean
}

export function DoorCodeCreateBasicsFields({
  codeType,
  onCodeTypeChange,
  label,
  onLabelChange,
  code,
  onCodeChange,
  maxUses,
  onMaxUsesChange,
  isBusy,
}: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <FormField label="Code type" htmlFor="door-code-create-type">
        <Select
          id="door-code-create-type"
          value={codeType}
          onChange={(e) => onCodeTypeChange(e.target.value as DoorCodeTypeOption)}
          disabled={isBusy}
        >
          <option value="permanent">Permanent</option>
          <option value="temporary">Temporary</option>
        </Select>
      </FormField>

      <FormField label="Label (optional)" htmlFor="door-code-create-label">
        <Input id="door-code-create-label" value={label} onChange={(e) => onLabelChange(e.target.value)} disabled={isBusy} />
      </FormField>

      <FormField
        label="Code (4–8 digits)"
        htmlFor="door-code-create-code"
        help="Codes are stored hashed on the server. Enter a 4–8 digit PIN; you cannot view it later."
        description="Codes are never shown again after creation."
        required
      >
        <Input
          id="door-code-create-code"
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          placeholder="••••"
          inputMode="numeric"
          autoComplete="one-time-code"
          disabled={isBusy}
        />
      </FormField>

      <FormField label="Max uses (optional)" htmlFor="door-code-create-max-uses" help="Leave blank for unlimited uses.">
        <Input
          id="door-code-create-max-uses"
          type="number"
          min={1}
          step={1}
          value={maxUses}
          onChange={(e) => onMaxUsesChange(e.target.value)}
          disabled={isBusy}
        />
      </FormField>
    </div>
  )
}

