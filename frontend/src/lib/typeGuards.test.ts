import { describe, expect, it } from 'vitest'
import {
  isAlarmEvent,
  isAlarmStatePayload,
  isAlarmStateType,
  isAlarmStateSnapshot,
  isCountdownPayload,
  isEventTypeType,
  isHealthPayload,
  isRecord,
  isStringArray,
  isStringRecord,
  isSystemStatusPayload,
} from '@/lib/typeGuards'

describe('typeGuards', () => {
  it('isRecord rejects arrays and null', () => {
    expect(isRecord(null)).toBe(false)
    expect(isRecord([])).toBe(false)
    expect(isRecord({})).toBe(true)
  })

  it('isStringRecord and isStringArray validate shapes', () => {
    expect(isStringRecord({ a: 'x' })).toBe(true)
    expect(isStringRecord({ a: 1 })).toBe(false)
    expect(isStringArray(['a', 'b'])).toBe(true)
    expect(isStringArray(['a', 1] as any)).toBe(false)
  })

  it('validates alarm and event enums', () => {
    expect(isAlarmStateType('armed_home')).toBe(true)
    expect(isAlarmStateType('nope')).toBe(false)
    expect(isEventTypeType('armed')).toBe(true)
    expect(isEventTypeType('nope')).toBe(false)
  })

  it('validates AlarmStateSnapshot and AlarmEvent', () => {
    expect(
      isAlarmStateSnapshot({
        id: 1,
        currentState: 'disarmed',
        previousState: null,
        settingsProfile: 1,
        enteredAt: 't',
        exitAt: null,
        lastTransitionReason: 'x',
        lastTransitionBy: null,
        targetArmedState: null,
        timingSnapshot: {},
      })
    ).toBe(true)

    expect(
      isAlarmEvent({
        id: 1,
        eventType: 'armed',
        stateFrom: null,
        stateTo: null,
        timestamp: 't',
        userId: null,
        codeId: null,
        sensorId: null,
        metadata: {},
      })
    ).toBe(true)
  })

  it('validates websocket payloads', () => {
    expect(
      isAlarmStatePayload({
        state: {
          id: 1,
          currentState: 'disarmed',
          previousState: null,
          settingsProfile: 1,
          enteredAt: 't',
          exitAt: null,
          lastTransitionReason: 'x',
          lastTransitionBy: null,
          targetArmedState: null,
          timingSnapshot: {},
        },
        effectiveSettings: { delayTime: 0, armingTime: 0, triggerTime: 0 },
      })
    ).toBe(true)

    expect(isCountdownPayload({ type: 'entry', remainingSeconds: 1, totalSeconds: 2 })).toBe(true)
    expect(isHealthPayload({ status: 'healthy', timestamp: 't' })).toBe(true)
    expect(
      isSystemStatusPayload({
        homeAssistant: { configured: true, reachable: true },
        mqtt: { configured: true, enabled: true, connected: true },
        zwavejs: { configured: true, enabled: true, connected: true },
        zigbee2mqtt: { enabled: true },
        frigate: { enabled: true, available: true },
      })
    ).toBe(true)
  })
})

