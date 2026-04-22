import { describe, expect, it } from 'vitest'

import {
  DOMAIN_STATE_SUGGESTIONS,
  getSuggestionsForDomain,
} from './domainStateSuggestions'

describe('getSuggestionsForDomain', () => {
  it('returns canonical states for binary_sensor', () => {
    expect(getSuggestionsForDomain('binary_sensor')).toEqual(['on', 'off'])
  })

  it('returns canonical states for lock', () => {
    expect(getSuggestionsForDomain('lock')).toEqual([
      'locked',
      'unlocked',
      'locking',
      'unlocking',
      'jammed',
      'unknown',
    ])
  })

  it('returns canonical states for cover', () => {
    expect(getSuggestionsForDomain('cover')).toEqual([
      'open',
      'closed',
      'opening',
      'closing',
      'stopped',
    ])
  })

  it('returns an empty list for sensor (arbitrary values)', () => {
    expect(getSuggestionsForDomain('sensor')).toEqual([])
  })

  it('returns an empty list for unknown domains', () => {
    expect(getSuggestionsForDomain('totally_made_up_domain')).toEqual([])
  })

  it('returns an empty list for undefined', () => {
    expect(getSuggestionsForDomain(undefined)).toEqual([])
  })

  it('returns an empty list for null', () => {
    expect(getSuggestionsForDomain(null)).toEqual([])
  })

  it('returns an empty list for empty string', () => {
    expect(getSuggestionsForDomain('')).toEqual([])
  })

  it('returns stable references across calls (no re-allocation)', () => {
    const a = getSuggestionsForDomain('light')
    const b = getSuggestionsForDomain('light')
    expect(a).toBe(b)

    const unknownA = getSuggestionsForDomain('nope')
    const unknownB = getSuggestionsForDomain(undefined)
    expect(unknownA).toBe(unknownB)
  })

  it('exposes a map entry for every HA domain with a curated list', () => {
    // Keep the exported map in sync with the ADR table — guard against
    // accidental deletions.
    const required = [
      'binary_sensor',
      'switch',
      'input_boolean',
      'light',
      'fan',
      'lock',
      'cover',
      'climate',
      'media_player',
      'person',
      'device_tracker',
      'sun',
      'alarm_control_panel',
    ]
    for (const domain of required) {
      const values = DOMAIN_STATE_SUGGESTIONS[domain]
      expect(values).toBeDefined()
      expect(values?.length ?? 0).toBeGreaterThan(0)
    }
  })
})
