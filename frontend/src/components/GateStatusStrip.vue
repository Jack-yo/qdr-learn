<template>
  <el-row :gutter="14">
    <el-col v-for="gate in gates" :key="gate.key" :xs="24" :sm="12" :lg="6" style="margin-bottom: 14px">
      <el-card shadow="hover" class="gate-card" @click="$emit('select', gate.route)">
        <div class="kpi-accent-bar" :style="{ background: accentHex(gate.status) }" />
        <div class="gate-top">
          <span class="gate-name">{{ gate.title }}</span>
          <el-tag :type="tagType(gate.status)" size="small" effect="light">{{ gate.status }}</el-tag>
        </div>
        <div class="gate-label" :style="{ color: labelHex(gate.status) }">{{ gate.label || 'N/A' }}</div>
        <div class="gate-detail">{{ gate.detail || '—' }}</div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
export interface GateItem { key: string; title: string; status: string; label: string; detail: string; route: string }
defineProps<{ gates: GateItem[] }>()
defineEmits<{ (e: 'select', route: string): void }>()

function tagType(s: string): 'success' | 'warning' | 'danger' | 'info' {
  const u = (s || '').toUpperCase()
  if (u === 'PASS' || u === 'OK' || u === 'READY') return 'success'
  if (u === 'BLOCKED' || u === 'ERROR') return 'danger'
  if (u === 'WARN' || u === 'DEGRADED') return 'warning'
  return 'info'
}
function accentHex(s: string): string {
  const u = (s || '').toUpperCase()
  if (u === 'PASS' || u === 'OK' || u === 'READY') return '#16a34a'
  if (u === 'BLOCKED' || u === 'ERROR') return '#dc2626'
  if (u === 'WARN' || u === 'DEGRADED') return '#d97706'
  return '#9ca3af'
}
function labelHex(s: string): string {
  const u = (s || '').toUpperCase()
  if (u === 'BLOCKED' || u === 'ERROR') return '#dc2626'
  if (u === 'WARN' || u === 'DEGRADED') return '#b45309'
  return '#111827'
}
</script>

<style scoped>
.gate-card { position: relative; cursor: pointer; overflow: hidden; }
.gate-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.gate-name { font-size: 12px; color: #6b7280; }
.gate-label { font-size: 16px; font-weight: 700; }
.gate-detail { margin-top: 4px; font-size: 12px; color: #4b5563; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
