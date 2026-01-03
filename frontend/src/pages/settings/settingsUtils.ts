import { AlarmState, AlarmStateLabels, type AlarmStateType } from '@/lib/constants'
import { isRecord } from '@/lib/typeGuards'

export const ARM_MODE_OPTIONS: AlarmStateType[] = [
  AlarmState.ARMED_AWAY,
  AlarmState.ARMED_HOME,
  AlarmState.ARMED_NIGHT,
  AlarmState.ARMED_VACATION,
  AlarmState.ARMED_CUSTOM_BYPASS,
]

export const ARM_MODE_TOOLTIPS: Record<AlarmStateType, string> = {
  [AlarmState.ARMED_HOME]: 'Typically perimeter-only protection while you are home.',
  [AlarmState.ARMED_AWAY]: 'Typically full protection when the home is empty.',
  [AlarmState.ARMED_NIGHT]: 'Typically like Home, but optimized for sleeping hours.',
  [AlarmState.ARMED_VACATION]: 'Typically like Away, plus extra deterrence/automations.',
  [AlarmState.ARMED_CUSTOM_BYPASS]:
    "Home Assistant-compatible 'custom bypass' mode. Intended for custom arming profiles where selected sensors are bypassed/ignored (e.g., allow certain rooms/motion). Requires explicit support/configuration in your setup.",
  [AlarmState.DISARMED]: 'All sensors inactive; no alarm triggers.',
  [AlarmState.ARMING]: 'Exit delay countdown before an armed mode becomes active.',
  [AlarmState.PENDING]: 'Entry delay countdown after an entry sensor trips.',
  [AlarmState.TRIGGERED]: 'Alarm is active/triggered.',
}

export const HA_NOTIFY_STATE_OPTIONS: AlarmStateType[] = [
  AlarmState.ARMING,
  AlarmState.ARMED_AWAY,
  AlarmState.ARMED_HOME,
  AlarmState.ARMED_NIGHT,
  AlarmState.ARMED_VACATION,
  AlarmState.PENDING,
  AlarmState.TRIGGERED,
  AlarmState.DISARMED,
]

export function parseNonNegativeInt(
  label: string,
  value: string
): { ok: true; value: number } | { ok: false; error: string } {
  if (value.trim() === '') return { ok: false, error: `${label} is required.` }
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) return { ok: false, error: `${label} must be a number.` }
  if (parsed < 0) return { ok: false, error: `${label} cannot be negative.` }
  return { ok: true, value: parsed }
}

export function parsePositiveInt(
  label: string,
  value: string
): { ok: true; value: number } | { ok: false; error: string } {
  const parsed = parseNonNegativeInt(label, value)
  if (!parsed.ok) return parsed
  if (parsed.value <= 0) return { ok: false, error: `${label} must be > 0.` }
  return parsed
}

export function toggleState(states: AlarmStateType[], state: AlarmStateType): AlarmStateType[] {
  if (states.includes(state)) return states.filter((s) => s !== state)
  return [...states, state]
}

export function normalizeStateOverrides(value: unknown): Record<string, Record<string, unknown>> {
  if (!isRecord(value)) return {}
  const out: Record<string, Record<string, unknown>> = {}
  for (const [rawKey, rawOverride] of Object.entries(value)) {
    if (!rawKey) continue
    const normalizedKey = rawKey.includes('_')
      ? rawKey
      : rawKey
          .replace(/([A-Z])/g, '_$1')
          .replace(/__/g, '_')
          .toLowerCase()
    if (!isRecord(rawOverride)) continue
    out[normalizedKey] = rawOverride
  }
  return out
}

export function formatArmStateLabel(state: AlarmStateType): string {
  return AlarmStateLabels[state] ?? state
}
