<template>
  <div v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">L1 市场状态预测 ({{ ctx.horizon }})</h1>
      <el-button @click="openRaw">L1 原始证据</el-button>
    </div>

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="12" :md="6" style="margin-bottom: 10px">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-accent-bar" style="background: #409eff" />
          <div class="kpi-label">市场状态</div>
          <div class="kpi-value" style="font-size: 18px">{{ summary?.regime || 'N/A' }}</div>
          <div class="kpi-sub">期望收益 <span :class="signClass(summary?.expected_return, ctx.colorMode)">{{ formatPct(summary?.expected_return) }}</span></div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6" style="margin-bottom: 10px">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-accent-bar" :style="{ background: probBarColor(summary?.up_probability) }" />
          <div class="kpi-label">上涨概率 ({{ ctx.horizon }})</div>
          <div class="kpi-value" :style="{ color: probBarColor(summary?.up_probability) }">{{ formatProb(summary?.up_probability) }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6" style="margin-bottom: 10px">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-accent-bar" style="background: #d97706" />
          <div class="kpi-label">显著下跌风险</div>
          <div class="kpi-value" :class="riskClass(Number(summary?.downside_risk ?? 0))">{{ formatProb(summary?.downside_risk) }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6" style="margin-bottom: 10px">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-accent-bar" style="background: #16a34a" />
          <div class="kpi-label">OOS Brier Score</div>
          <div class="kpi-value num-primary">{{ summary?.brier_score != null ? Number(summary.brier_score).toFixed(3) : 'N/A' }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="24" :xl="14" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">上涨概率 vs 显著下跌风险走势 (%)</span></template>
          <BaseChart :config="probChartConfig" :has-data="Boolean(probChartConfig)" :height="245" />
        </el-card>
      </el-col>
      <el-col :xs="24" :xl="10" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">六大市场体系标准化读数 (σ)</span></template>
          <BaseChart :config="dimChartConfig" :has-data="Boolean(dimChartConfig)" :height="245" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">未来 {{ ctx.horizon }} 收益分布概率 (%)</span></template>
          <BaseChart :config="distChartConfig" :has-data="Boolean(distChartConfig)" :height="220" />
        </el-card>
      </el-col>
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">概率校准曲线（预测 vs 样本外实际胜率）</span></template>
          <BaseChart :config="calChartConfig" :has-data="Boolean(calChartConfig)" :height="220" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header><span class="chart-card-title">市场观测维度明细</span></template>
      <el-table :data="dimensions" stripe>
        <el-table-column prop="system" label="体系" width="110" />
        <el-table-column prop="name" label="维度指标" min-width="180" />
        <el-table-column label="标准化读数" width="125">
          <template #default="{ row }">
            <span class="tabular-nums" :class="signClass(Number(row.score), ctx.colorMode)">
              {{ Number(row.score) > 0 ? '+' : '' }}{{ Number(row.score).toFixed(2) }}σ
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="115">
          <template #default="{ row }"><el-tag size="small" :type="Number(row.score) >= 0 ? 'success' : 'warning'">{{ row.state }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="110" />
        <el-table-column prop="freshness" label="更新时间" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import type { ChartConfiguration } from 'chart.js'
import { qdrApi } from '@/api/endpoints'
import { getDemoL1 } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { formatPct, formatProb, probBarColor, riskClass, signClass, upColorHex, downColorHex } from '@/utils/format'
import BaseChart from '@/components/BaseChart.vue'

const ctx = useContextStore()
const drawer = useDrawerStore()
const loading = ref(false)
const summary = ref<any>(null)
const dimensions = ref<any[]>([])

const probChartConfig = computed<ChartConfiguration | null>(() => {
  const h = summary.value?.history
  if (!h?.labels?.length) return null
  return {
    type: 'line',
    data: {
      labels: h.labels,
      datasets: [
        { label: `上涨概率 (${ctx.horizon})`, data: h.up, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.09)', fill: true, tension: 0.25, borderWidth: 2.2 },
        { label: `下跌风险 (${ctx.horizon})`, data: h.down, borderColor: '#d97706', backgroundColor: 'rgba(217,119,6,0.08)', fill: true, tension: 0.25, borderWidth: 2 },
      ],
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { min: 0, max: 80, grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const dimChartConfig = computed<ChartConfiguration | null>(() => {
  if (!dimensions.value.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: {
      labels: dimensions.value.map(d => d.system || d.name),
      datasets: [{ label: 'σ', data: dimensions.value.map(d => Number(d.score) || 0), backgroundColor: dimensions.value.map(d => (Number(d.score) >= 0 ? up : down)), borderRadius: 4 }],
    },
    options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { grid: { color: '#f1f5f9' } }, y: { grid: { display: false } } } },
  }
})

const distChartConfig = computed<ChartConfiguration | null>(() => {
  const d = summary.value?.ret_dist
  if (!d?.bins?.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: {
      labels: d.bins,
      datasets: [{ label: '概率 (%)', data: d.probs, backgroundColor: d.bins.map((b: string) => (b.startsWith('<') || b.startsWith('-') ? down : up)), borderRadius: 4 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const calChartConfig = computed<ChartConfiguration | null>(() => {
  const c = summary.value?.calibration
  if (!c?.bins?.length) return null
  return {
    type: 'line',
    data: {
      labels: c.bins,
      datasets: [
        { label: '理想校准线', data: c.predicted, borderColor: '#9ca3af', borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0 },
        { label: '实际 OOS 命中率', data: c.observed, borderColor: '#2563eb', borderWidth: 2.2, pointRadius: 3.5 },
      ],
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

async function load() {
  loading.value = true
  if (ctx.previewDemo) {
    const demo = getDemoL1(ctx.horizon)
    summary.value = demo; dimensions.value = demo.dimensions
    loading.value = false
    return
  }
  try {
    const res = await qdrApi.getL1Summary(ctx.horizon, ctx.tradingDate || undefined)
    const horizon = String(ctx.horizon).replace(/^H/, '')
    const evidence = res?.horizons?.[horizon]
    const estimates = evidence?.research_estimates || evidence?.admitted_probabilities || null
    summary.value = evidence ? {
      ...evidence,
      up_probability: estimates?.UP,
      downside_risk: estimates?.DOWN,
      brier_score: evidence?.validation?.model_brier,
      status: evidence?.status || res?.status,
      asof_session: res?.asof_session,
    } : null
    dimensions.value = Array.isArray(evidence?.trace?.feature_inputs)
      ? evidence.trace.feature_inputs.map((item: any) => ({
          system: item.name,
          name: item.key,
          score: item.standardized,
          state: evidence.status,
          source: res?.data_feed || res?.source,
          freshness: res?.asof_session || '—',
        }))
      : []
  } catch {
    summary.value = null; dimensions.value = []
  } finally {
    loading.value = false
  }
}

function openRaw() { drawer.openEvidence({ title: 'L1 原始证据', subtitle: 'GET /api/v1/l1/v3/overview', raw: summary.value }) }
watch(() => [ctx.tradingDate, ctx.horizon, ctx.previewDemo, ctx.refreshTick], load)
onMounted(load)
</script>
