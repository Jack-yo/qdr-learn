<template>
  <div v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">L4 持仓、风控与模拟复盘</h1>
      <el-button @click="jobsStore.runAction('reconcile', '模拟账本逐日对账')">执行逐日对账</el-button>
    </div>

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never"><template #header><span class="chart-card-title">个股浮动盈亏贡献 (%)</span></template><BaseChart :config="pnlChartConfig" :has-data="Boolean(pnlChartConfig)" :height="220" /></el-card>
      </el-col>
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never"><template #header><span class="chart-card-title">行业敞口 vs 30% 单行业上限</span></template><BaseChart :config="sectorChartConfig" :has-data="Boolean(sectorChartConfig)" :height="220" /></el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header><span class="chart-card-title">模拟持仓与止损监控</span></template>
      <el-table :data="positions" stripe @row-click="inspectPos">
        <el-table-column label="标的" width="110">
          <template #default="{ row }"><div style="font-weight: 700">{{ row.symbol }}</div><div style="font-size: 11px; color: #6b7280">{{ row.sector }}</div></template>
        </el-table-column>
        <el-table-column label="仓位" width="95"><template #default="{ row }"><span class="tabular-nums num-primary">{{ formatPct(row.weight, 1, false) }}</span></template></el-table-column>
        <el-table-column prop="entry_date" label="入场日" width="115" />
        <el-table-column label="入场价" width="105"><template #default="{ row }"><span class="tabular-nums">${{ Number(row.entry_price).toFixed(2) }}</span></template></el-table-column>
        <el-table-column label="浮动盈亏" width="115"><template #default="{ row }"><span class="tabular-nums" :class="signClass(Number(row.pnl_pct), ctx.colorMode)">{{ formatPct(row.pnl_pct) }}</span></template></el-table-column>
        <el-table-column label="距止损位" width="110"><template #default="{ row }"><span class="tabular-nums" :class="stopDistClass(Number(row.stop_dist_pct ?? -5))">{{ row.stop_dist_pct != null ? Number(row.stop_dist_pct).toFixed(1) + '%' : '—' }}</span></template></el-table-column>
        <el-table-column prop="exit_rule" label="退出条件" min-width="160" />
      </el-table>
    </el-card>

    <el-row :gutter="14">
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">持仓相关性热力矩阵</span></template>
          <el-table :data="corrRows" size="small" border>
            <el-table-column prop="symbol" label="标的" width="85" />
            <el-table-column v-for="sym in corrSymbols" :key="sym" :label="sym" min-width="75">
              <template #default="{ row }"><span class="corr-cell" :style="corrCellStyle(Number(row[sym]))">{{ Number(row[sym]).toFixed(2) }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">模拟成交流水与成本归因</span></template>
          <el-table :data="trades" size="small" stripe>
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column prop="symbol" label="标的" width="80" />
            <el-table-column prop="side" label="方向" min-width="135" />
            <el-table-column label="成交价" width="90"><template #default="{ row }"><span class="tabular-nums">${{ Number(row.price).toFixed(2) }}</span></template></el-table-column>
            <el-table-column label="成本" width="75"><template #default="{ row }"><span class="tabular-nums">{{ row.cost_bps }}bps</span></template></el-table-column>
            <el-table-column prop="status" label="状态" width="105" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import type { ChartConfiguration } from 'chart.js'
import { qdrApi } from '@/api/endpoints'
import { getDemoL4 } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { useJobsStore } from '@/stores/jobs'
import { formatPct, signClass, stopDistClass, upColorHex, downColorHex, corrCellStyle } from '@/utils/format'
import BaseChart from '@/components/BaseChart.vue'

const ctx = useContextStore()
const drawer = useDrawerStore()
const jobsStore = useJobsStore()

const loading = ref(false)
const positions = ref<any[]>([])
const sectorExposure = ref<any[]>([])
const corrSymbols = ref<string[]>([])
const corrRows = ref<any[]>([])
const trades = ref<any[]>([])

const pnlChartConfig = computed<ChartConfiguration | null>(() => {
  if (!positions.value.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: { labels: positions.value.map(p => p.symbol), datasets: [{ data: positions.value.map(p => Number(p.pnl_pct) || 0), backgroundColor: positions.value.map(p => (Number(p.pnl_pct) >= 0 ? up : down)), borderRadius: 4 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const sectorChartConfig = computed<ChartConfiguration | null>(() => {
  if (!sectorExposure.value.length) return null
  return {
    type: 'bar',
    data: { labels: sectorExposure.value.map(s => s.sector), datasets: [{ data: sectorExposure.value.map(s => s.current), backgroundColor: sectorExposure.value.map(s => (s.current >= 25 ? '#d97706' : '#409eff')), borderRadius: 4 }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { max: 35, grid: { color: '#f1f5f9' } }, y: { grid: { display: false } } } },
  }
})

async function load() {
  loading.value = true
  if (ctx.previewDemo) {
    const demo = getDemoL4()
    positions.value = demo.positions
    sectorExposure.value = demo.sector_exposure
    corrSymbols.value = demo.corr_matrix.symbols
    corrRows.value = demo.corr_matrix.rows
    trades.value = demo.trades
    loading.value = false
    return
  }
  try {
    const res = await qdrApi.getPaperLedger()
    positions.value = Array.isArray(res?.account?.positions) ? res.account.positions : Array.isArray(res?.positions) ? res.positions : []
    sectorExposure.value = Array.isArray(res?.sector_exposure) ? res.sector_exposure : []
    corrSymbols.value = Array.isArray(res?.corr_matrix?.symbols) ? res.corr_matrix.symbols : []
    corrRows.value = Array.isArray(res?.corr_matrix?.rows) ? res.corr_matrix.rows : []
    trades.value = Array.isArray(res?.trades) ? res.trades : []
  } catch {
    positions.value = []; sectorExposure.value = []; corrSymbols.value = []; corrRows.value = []; trades.value = []
  } finally {
    loading.value = false
  }
}

function inspectPos(row: any) { drawer.openEvidence({ title: `${row.symbol} 持仓详情`, raw: row }) }
watch(() => [ctx.previewDemo, ctx.refreshTick], load)
onMounted(load)
</script>
