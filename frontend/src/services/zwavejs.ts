import api from './api'
import type { ZwavejsSettings, ZwavejsSettingsUpdate, ZwavejsStatus, ZwavejsTestConnectionRequest } from '@/types'
import { apiEndpoints } from './endpoints'

export type ZwavejsNodeSummary = {
  nodeId: number
  name: string
  manufacturer: string | null
  productLabel: string | null
}

export type ZwavejsNodesResponse = {
  homeId: number | null
  nodes: ZwavejsNodeSummary[]
}

export const zwavejsService = {
  async getStatus(): Promise<ZwavejsStatus> {
    return api.get<ZwavejsStatus>(apiEndpoints.integrations.zwavejs.status)
  },

  async getNodes(): Promise<ZwavejsNodesResponse> {
    return api.get<ZwavejsNodesResponse>(apiEndpoints.integrations.zwavejs.nodes)
  },

  async getSettings(): Promise<ZwavejsSettings> {
    return api.get<ZwavejsSettings>(apiEndpoints.integrations.zwavejs.settings)
  },

  async updateSettings(changes: ZwavejsSettingsUpdate): Promise<ZwavejsSettings> {
    return api.patch<ZwavejsSettings>(apiEndpoints.integrations.zwavejs.settings, changes)
  },

  async testConnection(payload: ZwavejsTestConnectionRequest): Promise<{ ok: boolean }> {
    return api.post<{ ok: boolean }>(apiEndpoints.integrations.zwavejs.test, payload)
  },

  async syncEntities(): Promise<{ imported: number; updated: number; timestamp: string }> {
    return api.post<{ imported: number; updated: number; timestamp: string }>(
      apiEndpoints.integrations.zwavejs.syncEntities,
      {}
    )
  },
}

export default zwavejsService
