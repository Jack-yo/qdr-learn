<template>
  <div v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">L2 经典因子与风格轮动 ({{ ctx.horizon }})</h1>
      <el-checkbox v-model="onlySignificant" border size="small">仅看完整历史窗口</el-checkbox>
    </div>

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="24" :xl="8" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">风格代理 20 日相对收益</span></template>
          <BaseChart :config="barConfig" :has-data="Boolean(barConfig)" :height="240" />
        </el-card>
      </el-col>
      <el-col :xs="24" :xl="9" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">核心风格多日轮动轨迹</span></template>
          <BaseChart :config="trendConfig" :has-data="Boolean(trendConfig)" :height="240" />
        </el-card>
      </el-col>
      <el-col :xs="24" :xl="7" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">风格领先性检验 (Lead-Lag)</span></template>
          <BaseChart :config="leadLagConfig" :has-data="Boolean(leadLagConfig)" :height="240" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table :data="filteredRows" stripe @row-click="inspectFactor">
        <el-table-column label="风格因子" min-width="180">
          <template #default="{ row }">
            <div style="font-weight: 600">{{ row.name }}</div>
            <div style="font-size: 11px; color: #6b7280">{{ row.proxy || row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="5 日相对收益" width="130">
          <template #default="{ row }"><span class="tabular-nums" :class="signClass(Number(row.relative_return_5d), ctx.colorMode)">{{ Number(row.relative_return_5d * 100).toFixed(2) }}%</span></template>
        </el-table-column>
        <el-table-column label="20 日相对收益" width="140">
          <template #default="{ row }"><span class="tabular-nums" :class="signClass(Number(row.relative_return_20d), ctx.colorMode)">{{ Number(row.relative_return_20d * 100).toFixed(2) }}%</span></template>
        </el-table-column>
        <el-table-column label="60 日相对收益" width="140">
          <template #default="{ row }"><span class="tabular-nums" :class="signClass(Number(row.relative_return_60d), ctx.colorMode)">{{ Number(row.relative_return_60d * 100).toFixed(2) }}%</span></template>
        </el-table-column>
        <el-table-column prop="observation_status" label="状态" width="150" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import type { ChartConfiguration } from 'chart.js'
import { qdrApi } from '@/api/endpoints'
import { getDemoL2 } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { signClass, upColorHex, downColorHex } from '@/utils/format'
import BaseChart from '@/components/BaseChart.vue'

const ctx = useContextStore()
const drawer = useDrawerStore()
const loading = ref(false)
const onlySignificant = ref(false)
const rows = ref<any[]>([])
const trend = ref<any>(null)
const leadLag = ref<any>(null)

const filteredRows = computed(() => (onlySignificant.value ? rows.value.filter(r => r.complete_historical_window) : rows.value))

const barConfig = computed<ChartConfiguration | null>(() => {
  if (!filteredRows.value.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: {
      labels: filteredRows.value.map(r => r.style_name || r.style_id),
      datasets: [{ label: '20 日相对收益 (%)', data: filteredRows.value.map(r => Number(r.relative_return_20d) * 100 || 0), backgroundColor: filteredRows.value.map(r => (Number(r.relative_return_20d) >= 0 ? up : down)), borderRadius: 4 }],
    },
    options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { grid: { color: '#f1f5f9' } }, y: { grid: { display: false } } } },
  }
})

const trendConfig = computed<ChartConfiguration | null>(() => {
  if (!trend.value?.labels?.length) return null
  return {
    type: 'line',
    data: {
      labels: trend.value.labels,
      datasets: [
        { label: 'MOM', data: trend.value.MOM || [], borderColor: '#2563eb', tension: 0.25, borderWidth: 2 },
        { label: 'RMW', data: trend.value.RMW || [], borderColor: '#16a34a', tension: 0.25, borderWidth: 2 },
        { label: 'HML', data: trend.value.HML || [], borderColor: '#d97706', tension: 0.25, borderWidth: 2 },
      ],
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const leadLagConfig = computed<ChartConfiguration | null>(() => {
  if (!leadLag.value?.labels?.length) return null
  return {
    type: 'bar',
    data: {
      labels: leadLag.value.labels,
      datasets: [
        { label: 'MOM', data: leadLag.value.MOM || [], backgroundColor: '#2563eb', borderRadius: 3 },
        { label: 'RMW', data: leadLag.value.RMW || [], backgroundColor: '#16a34a', borderRadius: 3 },
      ],
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

async function load() {
  loading.value = true
  if (ctx.previewDemo) {
    const demo = getDemoL2(ctx.horizon)
    rows.value = demo.factors; trend.value = demo.trend; leadLag.value = demo.lead_lag
    loading.value = false
    return
  }
  try {
    const res = await qdrApi.getL2Styles(ctx.horizon)
    rows.value = Array.isArray(res?.latest) ? res.latest : []
    trend.value = null
    leadLag.value = null
  } catch {
    rows.value = []; trend.value = null; leadLag.value = null
  } finally {
    loading.value = false
  }
}

function inspectFactor(row: any) { drawer.openEvidence({ title: `${row.style_name || row.style_id} 诊断`, raw: row }) }
watch(() => [ctx.horizon, ctx.previewDemo, ctx.refreshTick], load)
onMounted(load)
</script>
