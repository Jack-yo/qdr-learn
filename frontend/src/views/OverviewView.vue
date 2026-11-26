<template>
  <div v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">盘后决策总览 · {{ ctx.tradingDate || dailyRaw?.trading_date || '最新' }} ({{ ctx.horizon }})</h1>
      <div style="display: flex; gap: 8px">
        <el-button @click="openEvidence">当日证据</el-button>
        <el-button type="primary" :disabled="Boolean(blockerTitle)" @click="freezeToday">冻结明日计划</el-button>
      </div>
    </div>

    <BlockerAlertBar :title="blockerTitle" :detail="blockerDetail" @fix="jobsStore.runAction('maintenance', '补数复检')" @goto-data="router.push('/data')" />
    <GateStatusStrip :gates="gates" @select="(p) => router.push(p)" />

    <el-row :gutter="14" style="margin-bottom: 14px">
      <el-col :xs="24" :xl="15" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header>
            <div class="chart-card-head">
              <span class="chart-card-title">前向模拟账本净值 vs SPY</span>
              <el-tag v-if="excessRet !== null" :type="excessRet >= 0 ? 'success' : 'danger'" effect="light">超额 {{ formatPct(excessRet) }}</el-tag>
            </div>
          </template>
          <BaseChart :config="ledgerChartConfig" :has-data="Boolean(ledgerChartConfig)" :height="240" />
        </el-card>
      </el-col>
      <el-col :xs="24" :xl="9" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">行业仓位与现金分布 (%)</span></template>
          <BaseChart :config="allocChartConfig" :has-data="Boolean(allocChartConfig)" :height="240" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header>
        <div class="chart-card-head">
          <span class="chart-card-title">明日候选清单</span>
          <el-button link type="primary" @click="router.push('/l3')">L3 明细 →</el-button>
        </div>
      </template>
      <el-table :data="candidates" stripe @row-click="openCandidate">
        <el-table-column prop="symbol" label="标的" width="115">
          <template #default="{ row }">
            <div style="font-weight: 700">{{ row.symbol }}</div>
            <div style="font-size: 11px; color: #6b7280">{{ row.sector || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'BLOCKED' ? 'danger' : row.status === 'ELIGIBLE' || row.status === 'FROZEN' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="`条件收益 (${ctx.horizon})`" width="130">
          <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.expected_return, ctx.colorMode)">{{ formatPct(row.expected_return) }}</span></template>
        </el-table-column>
        <el-table-column label="上涨概率" width="165">
          <template #default="{ row }">
            <div class="prob-cell">
              <span class="tabular-nums num-strong" :style="{ color: probBarColor(row.up_probability), width: '48px' }">{{ formatProb(row.up_probability) }}</span>
              <div class="prob-bar-bg"><div class="prob-bar-fill" :style="{ width: Math.min(100, probValue(row.up_probability)) + '%', background: probBarColor(row.up_probability) }" /></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="建议仓位" width="105">
          <template #default="{ row }"><span class="tabular-nums num-primary">{{ row.weight > 0 ? formatPct(row.weight, 1, false) : '—' }}</span></template>
        </el-table-column>
        <el-table-column prop="entry_rule" label="入场 / 备注" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-row :gutter="14">
      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">A / B / C / D 四层消融增量对比</span></template>
          <el-table :data="ablation" size="small" stripe>
            <el-table-column prop="tier" label="实验组" min-width="170" />
            <el-table-column label="OOS IC" width="90">
              <template #default="{ row }"><span class="tabular-nums num-primary">{{ Number(row.oos_ic).toFixed(3) }}</span></template>
            </el-table-column>
            <el-table-column label="ΔIC" width="90">
              <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.delta_ic, ctx.colorMode)">{{ row.delta_ic > 0 ? '+' : '' }}{{ Number(row.delta_ic).toFixed(3) }}</span></template>
            </el-table-column>
            <el-table-column label="Sharpe" width="85">
              <template #default="{ row }"><span class="tabular-nums num-ok">{{ Number(row.sharpe).toFixed(2) }}</span></template>
            </el-table-column>
            <el-table-column label="胜率" width="85">
              <template #default="{ row }"><span class="tabular-nums">{{ formatProb(row.win_rate) }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :xl="12" style="margin-bottom: 14px">
        <el-card shadow="never">
          <template #header><span class="chart-card-title">近期前向预测逐日评分卡</span></template>
          <el-table :data="scorecard" size="small" stripe>
            <el-table-column prop="date" label="冻结日" width="110" />
            <el-table-column prop="count" label="标的数" width="75" />
            <el-table-column label="预测均收益" width="100">
              <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.pred_ret, ctx.colorMode)">{{ formatPct(row.pred_ret) }}</span></template>
            </el-table-column>
            <el-table-column label="实际收益" width="100">
              <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.real_ret, ctx.colorMode)">{{ formatPct(row.real_ret) }}</span></template>
            </el-table-column>
            <el-table-column label="方向命中" width="90">
              <template #default="{ row }"><span class="tabular-nums num-strong">{{ formatProb(row.hit_rate) }}</span></template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="85" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import type { ChartConfiguration } from 'chart.js'
import { qdrApi } from '@/api/endpoints'
import { getDemoOverview } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { useJobsStore } from '@/stores/jobs'
import { formatPct, formatProb, probValue, probBarColor, signClass, upColorHex } from '@/utils/format'
import GateStatusStrip, { type GateItem } from '@/components/GateStatusStrip.vue'
import BlockerAlertBar from '@/components/BlockerAlertBar.vue'
import BaseChart from '@/components/BaseChart.vue'

const router = useRouter()
const ctx = useContextStore()
const drawer = useDrawerStore()
const jobsStore = useJobsStore()

const loading = ref(false)
const dailyRaw = ref<any>(null)
const planRaw = ref<any>(null)
const blockerTitle = ref('')
const blockerDetail = ref('')
const candidates = ref<any[]>([])
const ablation = ref<any[]>([])
const scorecard = ref<any[]>([])
const ledgerCurve = ref<{ labels: string[]; portfolio: number[]; benchmark: number[] } | null>(null)
const allocation = ref<{ name: string; value: number }[]>([])

const gates = ref<GateItem[]>([
  { key: 'l1', title: 'L1 市场状态', status: 'N/A', label: 'N/A', detail: '', route: '/l1' },
  { key: 'l2', title: 'L2 经典风格', status: 'N/A', label: 'N/A', detail: '', route: '/l2' },
  { key: 'l3', title: 'L3 个股 Alpha', status: 'N/A', label: 'N/A', detail: '', route: '/l3' },
  { key: 'l4', title: 'L4 持仓风控', status: 'N/A', label: 'N/A', detail: '', route: '/l4' },
])

const excessRet = computed(() => {
  const c = ledgerCurve.value
  if (!c?.portfolio?.length || !c?.benchmark?.length) return null
  return c.portfolio[c.portfolio.length - 1] - c.benchmark[c.benchmark.length - 1]
})

const ledgerChartConfig = computed<ChartConfiguration | null>(() => {
  const c = ledgerCurve.value
  if (!c?.labels?.length) return null
  return {
    type: 'line',
    data: {
      labels: c.labels,
      datasets: [
        { label: 'QDR 模拟组合', data: c.portfolio, borderColor: upColorHex(ctx.colorMode), backgroundColor: 'rgba(64,158,255,0.08)', fill: true, tension: 0.25, borderWidth: 2.2, pointRadius: 2.5 },
        { label: 'SPY 基准', data: c.benchmark, borderColor: '#9ca3af', borderDash: [4, 4], tension: 0.25, borderWidth: 1.6, pointRadius: 0 },
      ],
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const allocChartConfig = computed<ChartConfiguration | null>(() => {
  if (!allocation.value.length) return null
  return {
    type: 'doughnut',
    data: {
      labels: allocation.value.map(x => x.name),
      datasets: [{ data: allocation.value.map(x => x.value), backgroundColor: ['#409eff', '#16a34a', '#d97706', '#e5e7eb'], borderWidth: 2, borderColor: '#fff' }],
    },
    options: { cutout: '62%', plugins: { legend: { position: 'bottom' } } },
  }
})

async function load() {
  loading.value = true
  blockerTitle.value = ''
  blockerDetail.value = ''
  if (ctx.previewDemo) {
    const demo = getDemoOverview(ctx.horizon)
    dailyRaw.value = demo; planRaw.value = demo
    applyPayload(demo, demo, demo.scorecard)
    loading.value = false
    return
  }
  try {
    const [daily, plan, sc] = await Promise.all([
      qdrApi.getV4Daily(ctx.tradingDate || undefined),
      qdrApi.getV4Plan(ctx.horizon, ctx.tradingDate || undefined),
      qdrApi.getV4Scorecard().catch(() => null),
    ])
    dailyRaw.value = daily; planRaw.value = plan
    applyPayload(daily, plan, sc?.rows || sc?.items || [])
  } catch (err: any) {
    blockerTitle.value = '未连接本机后端 (127.0.0.1:8766)'
    blockerDetail.value = `${err?.message || '请求失败'}，可启动服务或打开顶栏「样例」开关预览。`
    candidates.value = []; ablation.value = []; scorecard.value = []; ledgerCurve.value = null; allocation.value = []
  } finally {
    loading.value = false
  }
}

function applyPayload(daily: any, plan: any, scRows: any[]) {
  const status = String(daily?.status || plan?.status || '').toUpperCase()
  if (status === 'BLOCKED' || daily?.blocked_reason) {
    blockerTitle.value = `BLOCKED：${daily?.blocked_reason || plan?.blocked_reason || '缺少合格数据'}`
    blockerDetail.value = '请补数并重新校验。'
  }
  const layers = daily?.layers || {}
  gates.value = [
    { key: 'l1', title: 'L1 市场状态', status: layers.l1?.status || 'N/A', label: layers.l1?.regime || layers.l1?.summary || 'N/A', detail: layers.l1?.detail || '', route: '/l1' },
    { key: 'l2', title: 'L2 经典风格', status: layers.l2?.status || 'N/A', label: layers.l2?.summary || 'N/A', detail: layers.l2?.detail || '', route: '/l2' },
    { key: 'l3', title: 'L3 个股 Alpha', status: layers.l3?.status || status || 'N/A', label: layers.l3?.summary || `${(plan?.candidates || []).length} 只候选`, detail: layers.l3?.detail || '', route: '/l3' },
    { key: 'l4', title: 'L4 持仓风控', status: layers.l4?.status || 'N/A', label: layers.l4?.summary || 'N/A', detail: layers.l4?.detail || '', route: '/l4' },
  ]
  candidates.value = Array.isArray(plan?.candidates) ? plan.candidates : []
  ablation.value = Array.isArray(daily?.ablation) ? daily.ablation : []
  scorecard.value = Array.isArray(scRows) ? scRows : []
  ledgerCurve.value = daily?.ledger_curve || null
  allocation.value = Array.isArray(daily?.allocation) ? daily.allocation : []
}

function openCandidate(row: any) {
  drawer.openEvidence({
    title: `${row.symbol} 归因与证据`,
    subtitle: `${ctx.tradingDate || '最新'} · ${ctx.horizon}`,
    items: [
      { label: '状态', value: String(row.status || 'N/A') },
      { label: '条件收益', value: formatPct(row.expected_return), mono: true },
      { label: '上涨概率', value: formatProb(row.up_probability), mono: true },
      { label: '建议仓位', value: formatPct(row.weight, 1, false), mono: true },
      { label: 'SHA256', value: String(row.sha256 || 'N/A'), mono: true },
    ],
    raw: row,
  })
}

function openEvidence() {
  drawer.openEvidence({
    title: '当日 Manifest 与证据',
    subtitle: dailyRaw.value?.bundle_id || 'N/A',
    items: [
      { label: '交易日', value: String(dailyRaw.value?.trading_date || 'N/A'), mono: true },
      { label: 'Bundle', value: String(dailyRaw.value?.bundle_id || 'N/A'), mono: true },
      { label: 'SHA256', value: String(dailyRaw.value?.manifest_sha256 || 'N/A'), mono: true },
    ],
    raw: { daily: dailyRaw.value, plan: planRaw.value },
  })
}

async function freezeToday() {
  try {
    await ElMessageBox.confirm('确认冻结当前计划？', '冻结确认', { type: 'warning' })
    await jobsStore.runAction('freeze_plan', '冻结明日研究计划', { horizon: ctx.horizon, date: ctx.tradingDate || undefined })
  } catch {}
}

watch(() => [ctx.tradingDate, ctx.horizon, ctx.previewDemo, ctx.refreshTick], load)
onMounted(load)
</script>
