import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { SECURITY_SETTINGS } from './SecuritySettingsCard'

function repoRootPath(...parts: string[]): string {
  const here = path.dirname(new URL(import.meta.url).pathname)
  return path.resolve(here, '../../../../../', ...parts)
}

describe('SecuritySettingsCard constants', () => {
  it('matches backend SystemConfig registry defaults for the alarm_code keys', () => {
    const settingsRegistryPath = repoRootPath('backend/alarm/settings_registry.py')
    const contents = readFileSync(settingsRegistryPath, 'utf-8')

    for (const setting of SECURITY_SETTINGS) {
      const key = setting.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const re = new RegExp(`SettingDefinition\\([\\s\\S]*?key="${key}"[\\s\\S]*?default=([0-9]+),`, 'm')
      const match = contents.match(re)
      expect(match, `Missing SettingDefinition for ${setting.key}`).not.toBeNull()
      const backendDefault = Number(match?.[1])
      expect(backendDefault).toBe(setting.defaultValue)
    }
  })
})
