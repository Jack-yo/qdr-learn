import type { ColorMode } from '@/stores/context'

export function normalizePct(val: unknown): number | null {
  if (typeof val !== 'number' || Number.isNaN(val)) return null
  return Math.abs(val) <= 1 ? val * 100 : val
}

export function formatPct(val: unknown, digits = 2, signed = true): string {
  const n = normalizePct(val)
  if (n === null) return 'N/A'
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

export function formatProb(val: unknown, digits = 1): string {
  if (typeof val !== 'number' || Number.isNaN(val)) return 'N/A'
  const n = val <= 1 ? val * 100 : val
  return `${n.toFixed(digits)}%`
}

export function probValue(val: unknown): number {
  if (typeof val !== 'number' || Number.isNaN(val)) return 0
  return val <= 1 ? val * 100 : val
}

export function probBarColor(val: unknown): string {
  const p = probValue(val)
  if (p >= 62) return '#16a34a'
  if (p >= 56) return '#409eff'
  if (p >= 50) return '#d97706'
  return '#dc2626'
}

export function signClass(val: unknown, mode: ColorMode): string {
  if (typeof val !== 'number' || Number.isNaN(val) || val === 0) return 'num-neutral'
  if (mode === 'us') return val > 0 ? 'num-up-us' : 'num-down-us'
  return val > 0 ? 'num-up-cn' : 'num-down-cn'
}

export function upColorHex(mode: ColorMode): string {
  return mode === 'us' ? '#16a34a' : '#dc2626'
}

export function downColorHex(mode: ColorMode): string {
  return mode === 'us' ? '#dc2626' : '#16a34a'
}

export function riskClass(pct: number): string {
  if (pct >= 20) return 'num-danger'
  if (pct >= 14) return 'num-warn'
  return 'num-ok'
}

export function stopDistClass(distPct: number): string {
  const absVal = Math.abs(distPct)
  if (absVal <= 2.0) return 'num-danger'
  if (absVal <= 3.0) return 'num-warn'
  return 'num-ok'
}

export function corrCellStyle(v: number): Record<string, string> {
  if (v >= 0.7) return { background: '#fee2e2', color: '#b91c1c' }
  if (v >= 0.45) return { background: '#fef3c7', color: '#b45309' }
  if (v <= -0.2) return { background: '#dcfce7', color: '#15803d' }
  return { background: '#f3f4f6', color: '#374151' }
}
