import { describe, expect, it } from 'vitest'
import { CustomValueEditor, RuleQueryBuilder } from './RuleQueryBuilder'

describe('RuleQueryBuilder', () => {
  it('imports', () => {
    expect(RuleQueryBuilder).toBeTruthy()
  })

  // Structural regression guard for PR #31.
  //
  // The bug: `CustomValueEditor` used to be defined inside the
  // `RuleQueryBuilder` function body and wrapped in `useCallback([context])`.
  // Every parent render that churned `context` (e.g. the `entities ?? []`
  // fallback during the TanStack query's loading→loaded transition)
  // produced a new function reference. react-querybuilder passed that
  // reference to `React.createElement` as the component *type*, so React
  // unmounted `EntityStateValueEditor` and reset its local `isOpen` to
  // false — closing the entity picker popover on the user's first click.
  //
  // The fix hoists `CustomValueEditor` to module scope so its identity is
  // permanent. This assertion pins that invariant: if someone moves the
  // dispatcher back inside the component body (or replaces it with a
  // `useCallback`/`useMemo` result), the named import below disappears and
  // this test fails loudly before the regression can ship.
  it('CustomValueEditor dispatcher lives at module scope', () => {
    expect(typeof CustomValueEditor).toBe('function')
    expect(CustomValueEditor.name).toBe('CustomValueEditor')
  })
})
