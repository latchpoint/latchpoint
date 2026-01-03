import { describe, expect, it } from 'vitest'
import {
  formatArmStateLabel,
  normalizeStateOverrides,
  parseNonNegativeInt,
  parsePositiveInt,
  toggleState,
} from '@/pages/settings/settingsUtils'
import { AlarmState } from '@/lib/constants'

describe('settingsUtils', () => {
  describe('parseNonNegativeInt', () => {
    it('rejects empty input', () => {
      expect(parseNonNegativeInt('Delay', '')).toEqual({ ok: false, error: 'Delay is required.' })
    })

    it('rejects non-numbers', () => {
      expect(parseNonNegativeInt('Delay', 'abc')).toEqual({ ok: false, error: 'Delay must be a number.' })
    })

    it('rejects negative numbers', () => {
      expect(parseNonNegativeInt('Delay', '-1')).toEqual({ ok: false, error: 'Delay cannot be negative.' })
    })

    it('accepts 0 and above', () => {
      expect(parseNonNegativeInt('Delay', '0')).toEqual({ ok: true, value: 0 })
      expect(parseNonNegativeInt('Delay', '5')).toEqual({ ok: true, value: 5 })
    })
  })

  describe('parsePositiveInt', () => {
    it('rejects 0', () => {
      expect(parsePositiveInt('Arming', '0')).toEqual({ ok: false, error: 'Arming must be > 0.' })
    })

    it('accepts > 0', () => {
      expect(parsePositiveInt('Arming', '1')).toEqual({ ok: true, value: 1 })
    })
  })

  describe('toggleState', () => {
    it('adds missing state', () => {
      expect(toggleState([AlarmState.ARMED_HOME], AlarmState.ARMED_AWAY)).toEqual([
        AlarmState.ARMED_HOME,
        AlarmState.ARMED_AWAY,
      ])
    })

    it('removes existing state', () => {
      expect(toggleState([AlarmState.ARMED_HOME, AlarmState.ARMED_AWAY], AlarmState.ARMED_HOME)).toEqual([
        AlarmState.ARMED_AWAY,
      ])
    })
  })

  describe('normalizeStateOverrides', () => {
    it('normalizes camelCase keys to snake_case and filters invalid entries', () => {
      const result = normalizeStateOverrides({
        armedHome: { arming_time: 10 },
        armed_away: { delay_time: 5 },
        '': { x: 1 },
        triggered: 'nope',
      })

      expect(result).toEqual({
        armed_home: { arming_time: 10 },
        armed_away: { delay_time: 5 },
      })
    })
  })

  describe('formatArmStateLabel', () => {
    it('returns a friendly label when known', () => {
      expect(formatArmStateLabel(AlarmState.ARMED_HOME)).toMatch(/home/i)
    })
  })
})

