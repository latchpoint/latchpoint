/** Domain → canonical HA state suggestions. See ADR-0086. */
export const DOMAIN_STATE_SUGGESTIONS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  binary_sensor: ['on', 'off'],
  switch: ['on', 'off'],
  input_boolean: ['on', 'off'],
  light: ['on', 'off'],
  fan: ['on', 'off'],
  lock: ['locked', 'unlocked', 'locking', 'unlocking', 'jammed', 'unknown'],
  cover: ['open', 'closed', 'opening', 'closing', 'stopped'],
  climate: ['off', 'heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only'],
  media_player: ['off', 'on', 'idle', 'playing', 'paused', 'standby', 'buffering'],
  person: ['home', 'not_home'],
  device_tracker: ['home', 'not_home'],
  sun: ['above_horizon', 'below_horizon'],
  alarm_control_panel: [
    'disarmed',
    'armed_home',
    'armed_away',
    'armed_night',
    'armed_vacation',
    'armed_custom_bypass',
    'pending',
    'arming',
    'triggered',
  ],
})

const EMPTY: readonly string[] = Object.freeze([])

export function getSuggestionsForDomain(domain: string | undefined | null): readonly string[] {
  if (!domain) return EMPTY
  return DOMAIN_STATE_SUGGESTIONS[domain] ?? EMPTY
}
