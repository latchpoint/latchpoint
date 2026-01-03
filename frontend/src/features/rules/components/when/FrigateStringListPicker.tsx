import { Button } from '@/components/ui/button'
import { DatalistInput } from '@/components/ui/datalist-input'
import { HelpTip } from '@/components/ui/help-tip'
import { IconButton } from '@/components/ui/icon-button'
import { Pill } from '@/components/ui/pill'
import { X } from 'lucide-react'

type Props = {
  label: string
  help: string
  listId: string
  options: string[]
  placeholder: string
  pickerValue: string
  setPickerValue: (next: string) => void
  values: string[]
  setValues: (next: string[]) => void
  disabled: boolean
}

export function FrigateStringListPicker({
  label,
  help,
  listId,
  options,
  placeholder,
  pickerValue,
  setPickerValue,
  values,
  setValues,
  disabled,
}: Props) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">
        {label} <HelpTip className="ml-1" content={help} />
      </label>
      <div className="flex gap-2">
        <DatalistInput
          listId={listId}
          options={options}
          value={pickerValue}
          onChange={(e) => setPickerValue(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
        />
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => {
            const toAdd = pickerValue.trim()
            if (!toAdd) return
            setValues(Array.from(new Set([...values, toAdd])))
            setPickerValue('')
          }}
        >
          Add
        </Button>
      </div>
      {values.length ? (
        <div className="flex flex-wrap gap-1 pt-1">
          {values.map((value) => (
            <Pill key={value} variant="muted" className="flex items-center gap-1">
              <span>{value}</span>
              <IconButton
                type="button"
                variant="ghost"
                aria-label={`Remove ${label.toLowerCase()} ${value}`}
                disabled={disabled}
                onClick={() => setValues(values.filter((x) => x !== value))}
              >
                <X className="h-3 w-3" />
              </IconButton>
            </Pill>
          ))}
        </div>
      ) : (
        <div className="pt-1 text-xs text-muted-foreground">None selected.</div>
      )}
    </div>
  )
}

