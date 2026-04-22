/** Domain → canonical HA state suggestions. See ADR-0086. */
export const DOMAIN_STATE_SUGGESTIONS: Readonly<Partial<Record<string, readonly string[]>>> = Object.freeze({
  binary_sensor: Object.freeze(['on', 'off']),
  switch: Object.freeze(['on', 'off']),
  input_boolean: Object.freeze(['on', 'off']),
  light: Object.freeze(['on', 'off']),
  fan: Object.freeze(['on', 'off']),
  lock: Object.freeze(['locked', 'unlocked', 'locking', 'unlocking', 'jammed', 'unknown']),
  cover: Object.freeze(['open', 'closed', 'opening', 'closing', 'stopped']),
  climate: Object.freeze(['off', 'heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only']),
  media_player: Object.freeze(['off', 'on', 'idle', 'playing', 'paused', 'standby', 'buffering']),
  person: Object.freeze(['home', 'not_home']),
  device_tracker: Object.freeze(['home', 'not_home']),
  sun: Object.freeze(['above_horizon', 'below_horizon']),
  alarm_control_panel: Object.freeze([
    'disarmed',
    'armed_home',
    'armed_away',
    'armed_night',
    'armed_vacation',
    'armed_custom_bypass',
    'pending',
    'arming',
    'triggered',
  ]),
})

const EMPTY: readonly string[] = Object.freeze([])

export function getSuggestionsForDomain(domain: string | undefined | null): readonly string[] {
  if (!domain) return EMPTY
  return DOMAIN_STATE_SUGGESTIONS[domain] ?? EMPTY
}
