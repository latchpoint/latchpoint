import { describe, expect, it } from 'vitest'

import {
  ALARM_TRIGGER_MAX_DELAY_SECONDS,
  isAlarmTriggerAction,
  isSendNotificationAction,
} from './ruleDefinition'

describe('ruleDefinition', () => {
  it('imports', async () => {
    const mod = await import('./ruleDefinition')
    expect(mod).toBeTruthy()
  })
})

describe('isAlarmTriggerAction', () => {
  it('accepts a bare alarm_trigger action without delaySeconds', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger' })).toBe(true)
  })

  it('accepts a valid integer delaySeconds in range', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: 0 })).toBe(true)
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: 15 })).toBe(true)
    expect(
      isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: ALARM_TRIGGER_MAX_DELAY_SECONDS }),
    ).toBe(true)
  })

  it('rejects delaySeconds above the max', () => {
    expect(
      isAlarmTriggerAction({
        type: 'alarm_trigger',
        delaySeconds: ALARM_TRIGGER_MAX_DELAY_SECONDS + 1,
      }),
    ).toBe(false)
  })

  it('rejects negative delaySeconds', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: -1 })).toBe(false)
  })

  it('rejects non-integer delaySeconds', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: 15.5 })).toBe(false)
  })

  it('rejects boolean delaySeconds (JS-level — bool is not number)', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: true as unknown as number })).toBe(false)
  })

  it('rejects string delaySeconds', () => {
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: '15' as unknown as number })).toBe(false)
  })

  it('rejects non-objects and wrong-type actions', () => {
    expect(isAlarmTriggerAction(null)).toBe(false)
    expect(isAlarmTriggerAction({ type: 'alarm_disarm' })).toBe(false)
  })
})

describe('isSendNotificationAction', () => {
  const base = { type: 'send_notification', providerId: 'p1', message: 'hi' }

  it('accepts a minimal send_notification action', () => {
    expect(isSendNotificationAction(base)).toBe(true)
  })

  it('accepts a valid integer delaySeconds in range', () => {
    expect(isSendNotificationAction({ ...base, delaySeconds: 0 })).toBe(true)
    expect(isSendNotificationAction({ ...base, delaySeconds: 30 })).toBe(true)
    expect(
      isSendNotificationAction({ ...base, delaySeconds: ALARM_TRIGGER_MAX_DELAY_SECONDS }),
    ).toBe(true)
  })

  it('rejects delaySeconds above the max', () => {
    expect(
      isSendNotificationAction({ ...base, delaySeconds: ALARM_TRIGGER_MAX_DELAY_SECONDS + 1 }),
    ).toBe(false)
  })

  it('rejects negative delaySeconds', () => {
    expect(isSendNotificationAction({ ...base, delaySeconds: -5 })).toBe(false)
  })

  it('rejects non-integer delaySeconds', () => {
    expect(isSendNotificationAction({ ...base, delaySeconds: 0.5 })).toBe(false)
  })

  it('rejects boolean delaySeconds', () => {
    expect(isSendNotificationAction({ ...base, delaySeconds: false as unknown as number })).toBe(false)
  })

  it('rejects when required fields are missing', () => {
    expect(isSendNotificationAction({ type: 'send_notification' })).toBe(false)
    expect(isSendNotificationAction({ type: 'send_notification', providerId: 'p1' })).toBe(false)
  })
})
