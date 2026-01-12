import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { SYSTEM_SETTINGS } from './SystemSettingsCard'

function repoRootPath(...parts: string[]): string {
  const here = path.dirname(new URL(import.meta.url).pathname)
  return path.resolve(here, '../../../../../', ...parts)
}

describe('SystemSettingsCard constants', () => {
  it('matches backend SystemConfig registry defaults for these keys', () => {
    const settingsRegistryPath = repoRootPath('backend/alarm/settings_registry.py')
    const contents = readFileSync(settingsRegistryPath, 'utf-8')

    for (const setting of SYSTEM_SETTINGS) {
      const key = setting.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const re = new RegExp(`SettingDefinition\\([\\s\\S]*?key="${key}"[\\s\\S]*?default=([0-9]+),`, 'm')
      const match = contents.match(re)
      expect(match, `Missing SettingDefinition for ${setting.key}`).not.toBeNull()
      const backendDefault = Number(match?.[1])
      expect(backendDefault).toBe(setting.defaultValue)
    }
  })
})
