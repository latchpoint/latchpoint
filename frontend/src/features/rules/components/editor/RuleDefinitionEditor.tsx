import { HelpTip } from '@/components/ui/help-tip'
import { Textarea } from '@/components/ui/textarea'

type Props = {
  advanced: boolean
  builderDefinitionText: string
  definitionText: string
  setDefinitionText: (next: string) => void
}

export function RuleDefinitionEditor({ advanced, builderDefinitionText, definitionText, setDefinitionText }: Props) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">
        Definition (JSON){' '}
        <HelpTip className="ml-1" content="The stored rule definition. Builder mode keeps this read-only; Advanced mode lets you edit it directly." />
      </label>
      <Textarea
        className="min-h-[220px] font-mono text-xs"
        value={advanced ? definitionText : builderDefinitionText}
        onChange={(e) => setDefinitionText(e.target.value)}
        spellCheck={false}
        disabled={!advanced}
      />
      {!advanced ? <div className="text-xs text-muted-foreground">JSON preview is read-only in Builder mode.</div> : null}
    </div>
  )
}

