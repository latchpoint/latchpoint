import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { RuleGroupType } from 'react-querybuilder'
import type { Entity } from '@/types/rules'
import { CustomValueEditor, RuleQueryBuilder } from './RuleQueryBuilder'

function makeEntity(entityId: string): Entity {
  return {
    id: 1,
    entityId,
    domain: entityId.split('.')[0] ?? 'sensor',
    name: entityId,
    deviceClass: null,
    lastState: null,
    lastChanged: null,
    lastSeen: null,
    attributes: {},
    source: 'home_assistant',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  }
}

function Harness({ entities }: { entities: Entity[] }) {
  const [query, setQuery] = useState<RuleGroupType>({
    combinator: 'and',
    rules: [
      {
        field: 'entity_state',
        operator: '=',
        value: { entityId: '', equals: 'on' },
      },
    ],
  })
  return (
    <RuleQueryBuilder query={query} onQueryChange={setQuery} entities={entities} />
  )
}

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
  // The fix hoists `CustomValueEditor` to module scope. This assertion
  // pins the stable contract: the dispatcher is exported from the module
  // as a function. The named import at the top of this file would fail at
  // module load if the export ever moved back inside the component body,
  // and the behavioral test below pins the user-visible symptom across
  // re-renders. We deliberately avoid asserting on `Function.name` since
  // bundlers/minifiers can rename functions and safe refactors (e.g.
  // wrapping the dispatcher in `React.memo`) would change the name while
  // preserving the actual invariant.
  it('CustomValueEditor dispatcher lives at module scope', () => {
    expect(typeof CustomValueEditor).toBe('function')
  })

  // Behavioral regression guard. The structural test above pins the
  // mechanism; this one pins the symptom. Open the entity picker, force a
  // parent re-render that churns the `entities` prop identity (simulating
  // TanStack Query's loading→loaded transition), and assert the popover
  // survives. If the value editor ever unmounts across a parent render,
  // its local `isOpen` resets to false and the search input disappears.
  it('keeps the entity picker popover open across parent re-renders', () => {
    const entitiesA = [makeEntity('binary_sensor.front_door')]
    const entitiesB = [makeEntity('binary_sensor.front_door')] // new array reference, same contents

    const { rerender } = render(<Harness entities={entitiesA} />)

    fireEvent.click(screen.getByRole('button', { name: /select entity/i }))
    expect(screen.getByPlaceholderText(/search entities/i)).toBeInTheDocument()

    rerender(<Harness entities={entitiesB} />)

    expect(screen.getByPlaceholderText(/search entities/i)).toBeInTheDocument()
  })
})
