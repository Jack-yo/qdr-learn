import { apiGet, apiPost } from './client'

export type Horizon = 'H1' | 'H3' | 'H5'
export interface GenericPayload { [key: string]: any }

export const qdrApi = {
  // Overview & V4 Daily / Scorecard / Signals
  getSystemStatus: () => apiGet<GenericPayload>('/api/v1/system/status'),
  getV4Daily: (date?: string) =>
    apiGet<GenericPayload>(`/api/v1/v4/daily${date ? `?date=${encodeURIComponent(date)}` : ''}`),
  getV4Plan: (horizon: Horizon, date?: string) =>
    apiGet<GenericPayload>('/api/v1/v4/plans'),
  getV4Scorecard: () => apiGet<GenericPayload>('/api/v1/v4/forward-scorecard'),
  getSignals: (date?: string) =>
    apiGet<GenericPayload>(`/api/v1/signals${date ? `?date=${encodeURIComponent(date)}` : ''}`),

  // L1 Market Regime
  getL1Summary: (horizon: Horizon, date?: string) =>
    apiGet<GenericPayload>('/api/v1/l1/v3/overview'),

  // L2 Classic Styles
  getL2Styles: (horizon: Horizon) =>
    apiGet<GenericPayload>('/api/v1/l2/styles/overview'),

  // L3 Stock Alpha, Factor Lab, Diagnostics & Strategies
  getL3Overview: (horizon: Horizon, date?: string) =>
    apiGet<GenericPayload>(`/api/v1/l3/overview?horizon=${encodeURIComponent(horizon)}${date ? `&date=${encodeURIComponent(date)}` : ''}`),
  setActiveStrategy: (strategyId: string) =>
    apiPost<GenericPayload>('/api/v1/l3/active-strategy', { strategy_id: strategyId }),
  getStrategies: () => apiGet<GenericPayload>('/api/v1/strategies'),
  validateStrategy: (id: string) => apiPost<GenericPayload>(`/api/v1/strategies/${encodeURIComponent(id)}/validate`),
  preflightStrategy: (id: string) => apiPost<GenericPayload>(`/api/v1/strategies/${encodeURIComponent(id)}/preflight`),
  freezeStrategy: (id: string) => apiPost<GenericPayload>(`/api/v1/strategies/${encodeURIComponent(id)}/freeze`),
  getFactors: () => apiGet<GenericPayload>('/api/v1/factor-lab/factors'),
  createFactor: (payload: { name: string; expression: string; description?: string }) =>
    apiPost<GenericPayload>('/api/v1/factor-lab/factors', payload),
  getExperiments: () => apiGet<GenericPayload>('/api/v1/factor-lab/experiments'),
  runFactorExperiment: (id: string) =>
    apiPost<GenericPayload>(`/api/v1/factor-lab/experiments/${encodeURIComponent(id)}/run`),

  // L4 Portfolio Risk & Paper Ledger
  getPaperLedger: () => apiGet<GenericPayload>('/api/v1/paper'),

  // Data Warehouse, Universe, Actions, Snapshots & Admission
  getWarehouseSummary: () => apiGet<GenericPayload>('/api/v1/warehouse/overview'),
  getDataCatalog: () => apiGet<GenericPayload>('/api/v1/data/catalog'),
  getDataUniverse: (date?: string) =>
    apiGet<GenericPayload>(`/api/v1/data/universe${date ? `?date=${encodeURIComponent(date)}` : ''}`),
  getDataActions: () => apiGet<GenericPayload>('/api/v1/data/actions'),
  getCloseSnapshots: () => apiGet<GenericPayload>('/api/v1/data/close-snapshots'),

  // Background Jobs & Actions
  getCurrentJobs: () => apiGet<GenericPayload>('/api/v1/jobs/current'),
  runAction: (action: string, payload?: Record<string, unknown>) =>
    apiPost<GenericPayload>(`/api/run/${encodeURIComponent(action)}`, payload),
}
