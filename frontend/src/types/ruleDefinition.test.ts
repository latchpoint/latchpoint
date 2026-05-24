import { describe, expect, it } from 'vitest'

import {
  ACTION_MAX_DELAY_SECONDS,
  ALARM_TRIGGER_MAX_DELAY_SECONDS,
  isAlarmSetStateAction,
  isAlarmTriggerAction,
  isControlPanelSetStateAction,
  isControlPanelTriggerAction,
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

  it('rejects any payload that includes delaySeconds (ADR-0094 §9 decision (a))', () => {
    // alarm_trigger is a pure "force TRIGGERED now" primitive. The guard
    // mirrors the backend validator — presence of the field is the rejection.
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: 0 })).toBe(false)
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: 15 })).toBe(false)
    expect(isAlarmTriggerAction({ type: 'alarm_trigger', delaySeconds: -1 })).toBe(false)
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

describe('isAlarmSetStateAction', () => {
  it('accepts every legal state without delaySeconds', () => {
    for (const state of [
      'disarmed',
      'pending',
      'triggered',
      'armed_home',
      'armed_away',
      'armed_night',
      'armed_vacation',
    ]) {
      expect(isAlarmSetStateAction({ type: 'alarm_set_state', state })).toBe(true)
    }
  })

  it('accepts a valid integer delaySeconds in range (ADR-0094 generic delay)', () => {
    expect(
      isAlarmSetStateAction({ type: 'alarm_set_state', state: 'triggered', delaySeconds: 0 }),
    ).toBe(true)
    expect(
      isAlarmSetStateAction({
        type: 'alarm_set_state',
        state: 'triggered',
        delaySeconds: ACTION_MAX_DELAY_SECONDS,
      }),
    ).toBe(true)
  })

  it('rejects unknown or non-string state values', () => {
    expect(isAlarmSetStateAction({ type: 'alarm_set_state', state: 'arming' })).toBe(false)
    expect(isAlarmSetStateAction({ type: 'alarm_set_state', state: 'bogus' })).toBe(false)
    expect(isAlarmSetStateAction({ type: 'alarm_set_state' })).toBe(false)
    expect(isAlarmSetStateAction({ type: 'alarm_set_state', state: 42 })).toBe(false)
  })

  it('rejects invalid delaySeconds (negative, above max, non-integer, boolean)', () => {
    const base = { type: 'alarm_set_state', state: 'triggered' }
    expect(isAlarmSetStateAction({ ...base, delaySeconds: -1 })).toBe(false)
    expect(
      isAlarmSetStateAction({ ...base, delaySeconds: ACTION_MAX_DELAY_SECONDS + 1 }),
    ).toBe(false)
    expect(isAlarmSetStateAction({ ...base, delaySeconds: 1.5 })).toBe(false)
    expect(
      isAlarmSetStateAction({ ...base, delaySeconds: true as unknown as number }),
    ).toBe(false)
  })

  it('rejects non-objects and wrong action types', () => {
    expect(isAlarmSetStateAction(null)).toBe(false)
    expect(isAlarmSetStateAction({ type: 'alarm_trigger' })).toBe(false)
  })
})

describe('isControlPanelSetStateAction', () => {
  const base = { type: 'control_panel_set_state', panelId: 1, state: 'pending' }

  it('accepts every legal indicator state', () => {
    for (const state of ['pending', 'disarmed', 'armed_stay', 'armed_away', 'triggered', 'auto']) {
      expect(isControlPanelSetStateAction({ ...base, state })).toBe(true)
    }
  })

  it('accepts a valid countdownSeconds in range', () => {
    expect(isControlPanelSetStateAction({ ...base, countdownSeconds: 0 })).toBe(true)
    expect(
      isControlPanelSetStateAction({ ...base, countdownSeconds: ACTION_MAX_DELAY_SECONDS }),
    ).toBe(true)
  })

  it('rejects invalid panelId (missing, zero, negative, non-integer, boolean)', () => {
    expect(isControlPanelSetStateAction({ type: 'control_panel_set_state', state: 'pending' })).toBe(false)
    expect(isControlPanelSetStateAction({ ...base, panelId: 0 })).toBe(false)
    expect(isControlPanelSetStateAction({ ...base, panelId: -3 })).toBe(false)
    expect(isControlPanelSetStateAction({ ...base, panelId: 1.5 })).toBe(false)
    // booleans pass typeof === 'number' check? no, typeof true === 'boolean' — the
    // guard already rejects via the integer/positive check. Spot-check anyway.
    expect(
      isControlPanelSetStateAction({ ...base, panelId: true as unknown as number }),
    ).toBe(false)
  })

  it('rejects unknown state', () => {
    expect(isControlPanelSetStateAction({ ...base, state: 'bogus' })).toBe(false)
    expect(isControlPanelSetStateAction({ ...base, state: undefined })).toBe(false)
  })

  it('rejects invalid countdownSeconds (negative, above max, non-integer)', () => {
    expect(isControlPanelSetStateAction({ ...base, countdownSeconds: -1 })).toBe(false)
    expect(
      isControlPanelSetStateAction({ ...base, countdownSeconds: ACTION_MAX_DELAY_SECONDS + 1 }),
    ).toBe(false)
    expect(isControlPanelSetStateAction({ ...base, countdownSeconds: 1.5 })).toBe(false)
  })

  it('rejects wrong action types', () => {
    expect(isControlPanelSetStateAction({ type: 'control_panel_trigger', panelId: 1 })).toBe(false)
    expect(isControlPanelSetStateAction(null)).toBe(false)
  })
})

describe('isControlPanelTriggerAction', () => {
  const base = { type: 'control_panel_trigger', panelId: 1 }

  it('accepts a minimal control_panel_trigger', () => {
    expect(isControlPanelTriggerAction(base)).toBe(true)
  })

  it('accepts a valid delaySeconds (ADR-0094 generic delay)', () => {
    expect(isControlPanelTriggerAction({ ...base, delaySeconds: 30 })).toBe(true)
    expect(
      isControlPanelTriggerAction({ ...base, delaySeconds: ACTION_MAX_DELAY_SECONDS }),
    ).toBe(true)
  })

  it('rejects invalid panelId', () => {
    expect(isControlPanelTriggerAction({ type: 'control_panel_trigger' })).toBe(false)
    expect(isControlPanelTriggerAction({ ...base, panelId: 0 })).toBe(false)
    expect(isControlPanelTriggerAction({ ...base, panelId: -1 })).toBe(false)
    expect(isControlPanelTriggerAction({ ...base, panelId: 1.5 })).toBe(false)
  })

  it('rejects invalid delaySeconds', () => {
    expect(isControlPanelTriggerAction({ ...base, delaySeconds: -1 })).toBe(false)
    expect(
      isControlPanelTriggerAction({ ...base, delaySeconds: ACTION_MAX_DELAY_SECONDS + 1 }),
    ).toBe(false)
    expect(
      isControlPanelTriggerAction({ ...base, delaySeconds: true as unknown as number }),
    ).toBe(false)
  })

  it('rejects wrong action types', () => {
    expect(isControlPanelTriggerAction({ type: 'control_panel_set_state', panelId: 1 })).toBe(false)
    expect(isControlPanelTriggerAction(null)).toBe(false)
  })
})
