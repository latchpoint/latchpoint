/**
 * Mutable in-memory stores. Module-level `let` bindings — a hard refresh
 * re-imports the module and re-initializes from fixtures, so refresh resets
 * state automatically (the "no persistence" guarantee from ADR-0089).
 */

import {
  demoAlarmState,
  demoAlarmSettings,
  demoAlarmProfiles,
  demoIntegrationHealth,
  demoSensors,
  demoUserCodes,
  demoDoorCodes,
  demoRules,
  demoEvents,
  demoNotificationProviders,
  demoControlPanels,
  demoSchedulerTasks,
  demoZwaveNodes,
  demoZigbeeDevices,
  demoFrigateCameras,
  demoFrigateDetections,
  demoHaEntities,
} from './fixtures'

export const stores = {
  alarmState: { ...demoAlarmState } as Record<string, unknown>,
  alarmSettings: { ...demoAlarmSettings } as Record<string, unknown>,
  alarmProfiles: [...demoAlarmProfiles] as Array<Record<string, unknown>>,
  integrationHealth: structuredClone(demoIntegrationHealth) as Record<string, Record<string, unknown>>,
  sensors: structuredClone(demoSensors) as Array<Record<string, unknown>>,
  userCodes: structuredClone(demoUserCodes) as Array<Record<string, unknown>>,
  doorCodes: structuredClone(demoDoorCodes) as Array<Record<string, unknown>>,
  rules: structuredClone(demoRules) as Array<Record<string, unknown>>,
  events: structuredClone(demoEvents) as Array<Record<string, unknown>>,
  notificationProviders: structuredClone(demoNotificationProviders) as Array<Record<string, unknown>>,
  controlPanels: structuredClone(demoControlPanels) as Array<Record<string, unknown>>,
  schedulerTasks: structuredClone(demoSchedulerTasks) as Array<Record<string, unknown>>,
  zwaveNodes: structuredClone(demoZwaveNodes) as Array<Record<string, unknown>>,
  zigbeeDevices: structuredClone(demoZigbeeDevices) as Array<Record<string, unknown>>,
  frigateCameras: structuredClone(demoFrigateCameras) as Array<Record<string, unknown>>,
  frigateDetections: structuredClone(demoFrigateDetections) as Array<Record<string, unknown>>,
  haEntities: structuredClone(demoHaEntities) as Array<Record<string, unknown>>,
}

let nextId = 10_000

export function nextDemoId(): number {
  return nextId++
}
