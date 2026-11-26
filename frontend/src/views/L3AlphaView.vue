<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">L3 个股 Alpha · {{ activeStrategyId || '未激活策略' }}</h1>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- Tab 1: Screen & Basket -->
        <el-tab-pane label="每日选股与组合" name="screen">
          <div style="display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; justify-content: space-between">
            <div style="display: flex; gap: 8px; flex-wrap: wrap">
              <el-input v-model="search" placeholder="搜索代码或行业..." clearable style="width: 200px" />
              <el-select v-model="statusFilter" style="width: 130px">
                <el-option label="全部状态" value="ALL" />
                <el-option label="合格可交易" value="ELIGIBLE" />
                <el-option label="观察" value="WATCH" />
              </el-select>
            </div>
            <div style="display: flex; gap: 8px; align-items: center">
              <span style="font-size: 12px; color: #6b7280">已勾选 <strong>{{ selectedRows.length }}</strong> 只</span>
              <el-button size="small" :disabled="!selectedRows.length" @click="runBasketPreflight">组合预检</el-button>
              <el-button size="small" type="primary" @click="loadL3">刷新</el-button>
            </div>
          </div>

          <div style="margin-bottom: 14px">
            <BaseChart :config="candBarConfig" :has-data="Boolean(candBarConfig)" :height="185" />
          </div>

          <el-table :data="filteredCandidates" v-loading="loading" stripe @selection-change="(val: any[]) => selectedRows = val" @row-click="inspectCandidate">
            <el-table-column type="selection" width="44" />
            <el-table-column label="标的" width="115">
              <template #default="{ row }">
                <div style="font-weight: 700">{{ row.symbol }}</div>
                <div style="font-size: 11px; color: #6b7280">{{ row.sector || '—' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag size="small" :type="row.status === 'ELIGIBLE' ? 'success' : row.status === 'BLOCKED' ? 'danger' : 'info'">{{ row.status }}</el-tag></template>
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
        </el-tab-pane>

        <!-- Tab 2: Factor Lab + Diagnostics -->
        <el-tab-pane label="自定义因子实验室" name="lab">
          <el-row :gutter="16">
            <el-col :xs="24" :lg="10" style="margin-bottom: 14px">
              <el-form label-position="top">
                <el-form-item label="因子名称"><el-input v-model="factorForm.name" /></el-form-item>
                <el-form-item label="受限 DSL 表达式"><el-input v-model="factorForm.expression" type="textarea" :rows="3" /></el-form-item>
                <el-form-item><el-button type="primary" :loading="savingFactor" @click="saveFactor">保存并运行实验</el-button></el-form-item>
              </el-form>

              <div style="font-size: 13px; font-weight: 600; margin: 12px 0 8px">因子冗余与相关性诊断</div>
              <el-table :data="factorDiag?.redundancy || []" size="small" stripe>
                <el-table-column prop="pair" label="因子对" min-width="150" />
                <el-table-column label="相关系数" width="90">
                  <template #default="{ row }"><span class="corr-cell" :style="corrCellStyle(Number(row.corr))">{{ Number(row.corr).toFixed(2) }}</span></template>
                </el-table-column>
                <el-table-column prop="verdict" label="结论" width="90" />
              </el-table>
            </el-col>

            <el-col :xs="24" :lg="14" style="margin-bottom: 14px">
              <el-row :gutter="12" style="margin-bottom: 12px">
                <el-col :span="8"><el-card shadow="never"><div class="kpi-label">Rank IC</div><div class="kpi-value num-primary">{{ factorDiag ? factorDiag.ic.toFixed(3) : 'N/A' }}</div></el-card></el-col>
                <el-col :span="8"><el-card shadow="never"><div class="kpi-label">ICIR</div><div class="kpi-value num-ok">{{ factorDiag ? factorDiag.icir.toFixed(2) : 'N/A' }}</div></el-card></el-col>
                <el-col :span="8"><el-card shadow="never"><div class="kpi-label">日均换手率</div><div class="kpi-value num-warn">{{ factorDiag ? factorDiag.turnover.toFixed(1) + '%' : 'N/A' }}</div></el-card></el-col>
              </el-row>
              <el-row :gutter="12">
                <el-col :xs="24" :md="12" style="margin-bottom: 12px">
                  <el-card shadow="never"><template #header><span class="chart-card-title">五分组单调性收益 (%)</span></template><BaseChart :config="quantileChartConfig" :has-data="Boolean(quantileChartConfig)" :height="200" /></el-card>
                </el-col>
                <el-col :xs="24" :md="12" style="margin-bottom: 12px">
                  <el-card shadow="never"><template #header><span class="chart-card-title">滚动 OOS Rank IC</span></template><BaseChart :config="rollingIcConfig" :has-data="Boolean(rollingIcConfig)" :height="200" /></el-card>
                </el-col>
              </el-row>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- Tab 3: Strategies & Walk-Forward Backtest -->
        <el-tab-pane label="策略与模拟回测" name="strategy">
          <el-row :gutter="14" style="margin-bottom: 14px">
            <el-col :xs="24" :lg="14" style="margin-bottom: 14px">
              <el-card shadow="never"><template #header><span class="chart-card-title">Walk-Forward 净值曲线对比</span></template><BaseChart :config="strategyNavConfig" :has-data="Boolean(strategyNavConfig)" :height="220" /></el-card>
            </el-col>
            <el-col :xs="24" :lg="10" style="margin-bottom: 14px">
              <el-card shadow="never"><template #header><span class="chart-card-title">水下回撤对比 (%)</span></template><BaseChart :config="strategyDdConfig" :has-data="Boolean(strategyDdConfig)" :height="220" /></el-card>
            </el-col>
          </el-row>

          <el-table :data="strategies" v-loading="loading" stripe>
            <el-table-column prop="id" label="策略 ID" width="150" />
            <el-table-column prop="name" label="名称" min-width="190" />
            <el-table-column label="OOS Sharpe" width="110">
              <template #default="{ row }"><span class="tabular-nums" :class="Number(row.oos_sharpe) >= 1.2 ? 'num-ok' : 'num-primary'">{{ row.oos_sharpe != null ? Number(row.oos_sharpe).toFixed(2) : 'N/A' }}</span></template>
            </el-table-column>
            <el-table-column label="最大回撤" width="105">
              <template #default="{ row }"><span class="tabular-nums num-danger">{{ formatPct(row.max_dd) }}</span></template>
            </el-table-column>
            <el-table-column label="胜率" width="90">
              <template #default="{ row }"><span class="tabular-nums num-strong">{{ formatProb(row.win_rate) }}</span></template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" :type="row.status === 'FROZEN' ? 'primary' : row.status === 'VALIDATED' ? 'success' : 'info'">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button size="small" @click="activateStrategy(row.id)">激活</el-button>
                <el-button size="small" @click="runStrategyAction(row.id, 'preflight')">预检</el-button>
                <el-button size="small" type="primary" @click="runStrategyAction(row.id, 'freeze')">冻结</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Tab 4: Signal History -->
        <el-tab-pane label="历史信号与复盘" name="signals">
          <el-table :data="signalHistory" stripe>
            <el-table-column prop="date" label="信号日" width="120" />
            <el-table-column prop="symbol" label="标的" width="100" />
            <el-table-column prop="horizon" label="周期" width="80" />
            <el-table-column label="预测收益" width="120">
              <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.pred_ret, ctx.colorMode)">{{ formatPct(row.pred_ret) }}</span></template>
            </el-table-column>
            <el-table-column label="实际收益" width="120">
              <template #default="{ row }"><span class="tabular-nums" :class="signClass(row.real_ret, ctx.colorMode)">{{ formatPct(row.real_ret) }}</span></template>
            </el-table-column>
            <el-table-column label="结果" width="100">
              <template #default="{ row }"><el-tag size="small" :type="row.status === '命中' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ChartConfiguration } from 'chart.js'
import { qdrApi } from '@/api/endpoints'
import { getDemoL3 } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { useJobsStore } from '@/stores/jobs'
import { formatPct, formatProb, probValue, probBarColor, signClass, upColorHex, downColorHex, corrCellStyle } from '@/utils/format'
import BaseChart from '@/components/BaseChart.vue'

const route = useRoute()
const ctx = useContextStore()
const drawer = useDrawerStore()
const jobsStore = useJobsStore()

const activeTab = ref<string>(String(route.query.tab || 'screen'))
const activeStrategyId = ref('')
const loading = ref(false)
const search = ref('')
const statusFilter = ref('ALL')
const selectedRows = ref<any[]>([])
const candidates = ref<any[]>([])
const strategies = ref<any[]>([])
const signalHistory = ref<any[]>([])
const factorDiag = ref<any>(null)
const factorForm = ref({ name: 'mom20_vol_adj_v2', expression: 'rank(ts_ret(close, 20) / (ts_std(ret1, 20) + 1e-6)) - 0.3 * rank(ts_ret(close, 5))' })
const savingFactor = ref(false)

const filteredCandidates = computed(() => {
  let list = candidates.value
  if (statusFilter.value !== 'ALL') list = list.filter(c => c.status === statusFilter.value)
  const q = search.value.trim().toLowerCase()
  if (q) list = list.filter(c => String(c.symbol || '').toLowerCase().includes(q) || String(c.sector || '').toLowerCase().includes(q))
  return list
})

const candBarConfig = computed<ChartConfiguration | null>(() => {
  if (!filteredCandidates.value.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: {
      labels: filteredCandidates.value.map(c => c.symbol),
      datasets: [{ label: `条件收益 (${ctx.horizon}, %)`, data: filteredCandidates.value.map(c => Number(c.expected_return) || 0), backgroundColor: filteredCandidates.value.map(c => (Number(c.expected_return) >= 0 ? up : down)), borderRadius: 4 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const quantileChartConfig = computed<ChartConfiguration | null>(() => {
  const qs = factorDiag.value?.quantiles
  if (!Array.isArray(qs) || !qs.length) return null
  const up = upColorHex(ctx.colorMode), down = downColorHex(ctx.colorMode)
  return {
    type: 'bar',
    data: { labels: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], datasets: [{ data: qs, backgroundColor: qs.map((v: number) => (v >= 0 ? up : down)), borderRadius: 4 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const rollingIcConfig = computed<ChartConfiguration | null>(() => {
  const ic = factorDiag.value?.rolling_ic
  if (!Array.isArray(ic) || !ic.length) return null
  return {
    type: 'line',
    data: { labels: factorDiag.value.rolling_ic_labels || ic.map((_: any, i: number) => `W${i + 1}`), datasets: [{ label: 'Rank IC', data: ic, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.08)', fill: true, tension: 0.25, borderWidth: 2 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const strategyNavConfig = computed<ChartConfiguration | null>(() => {
  const withNav = strategies.value.filter(s => Array.isArray(s.nav) && s.nav.length)
  if (!withNav.length) return null
  const colors = ['#2563eb', '#16a34a', '#d97706']
  return {
    type: 'line',
    data: {
      labels: withNav[0].nav.map((_: any, i: number) => `T+${i + 1}`),
      datasets: withNav.map((s, idx) => ({ label: s.id, data: s.nav, borderColor: colors[idx % colors.length], tension: 0.25, borderWidth: 2 })),
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

const strategyDdConfig = computed<ChartConfiguration | null>(() => {
  const withDd = strategies.value.filter(s => Array.isArray(s.dd) && s.dd.length)
  if (!withDd.length) return null
  const colors = ['#dc2626', '#d97706', '#6b7280']
  return {
    type: 'line',
    data: {
      labels: withDd[0].dd.map((_: any, i: number) => `T+${i + 1}`),
      datasets: withDd.map((s, idx) => ({ label: s.id, data: s.dd, borderColor: colors[idx % colors.length], backgroundColor: 'rgba(220,38,38,0.06)', fill: true, tension: 0.2, borderWidth: 1.8 })),
    },
    options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { grid: { color: '#f1f5f9' } }, x: { grid: { display: false } } } },
  }
})

async function loadL3() {
  loading.value = true
  if (ctx.previewDemo) {
    const demo = getDemoL3(ctx.horizon)
    activeStrategyId.value = demo.active_strategy_id
    candidates.value = demo.candidates
    strategies.value = demo.strategies
    factorDiag.value = demo.factor_diag
    signalHistory.value = demo.signal_history
    loading.value = false
    return
  }
  try {
    const [ov, st, sig] = await Promise.all([
      qdrApi.getL3Overview(ctx.horizon, ctx.tradingDate || undefined),
      qdrApi.getStrategies(),
      qdrApi.getSignals(ctx.tradingDate || undefined).catch(() => null),
    ])
    activeStrategyId.value = ov?.active_strategy_id || ''
    candidates.value = Array.isArray(ov?.candidates) ? ov.candidates : []
    strategies.value = Array.isArray(st?.strategies) ? st.strategies : Array.isArray(st) ? st : []
    factorDiag.value = ov?.factor_diag || null
    signalHistory.value = Array.isArray(sig?.signals) ? sig.signals : Array.isArray(sig) ? sig : []
  } catch {
    candidates.value = []; strategies.value = []; factorDiag.value = null; signalHistory.value = []
  } finally {
    loading.value = false
  }
}

async function saveFactor() {
  if (!factorForm.value.name.trim() || !factorForm.value.expression.trim()) { ElMessage.warning('请填写名称和公式'); return }
  savingFactor.value = true
  try {
    await qdrApi.createFactor({ name: factorForm.value.name.trim(), expression: factorForm.value.expression.trim() })
    ElMessage.success('因子已保存')
  } catch (err: any) { ElMessage.error(err?.message || '保存失败') }
  finally { savingFactor.value = false }
}

async function activateStrategy(id: string) {
  try {
    await qdrApi.setActiveStrategy(id)
    activeStrategyId.value = id
    ElMessage.success(`已激活策略：${id}`)
  } catch (err: any) { ElMessage.error(err?.message || '激活失败') }
}

async function runStrategyAction(id: string, op: 'preflight' | 'freeze') {
  try {
    if (op === 'preflight') await qdrApi.preflightStrategy(id)
    else await qdrApi.freezeStrategy(id)
    ElMessage.success(`${id} ${op === 'preflight' ? '预检' : '冻结'}完成`)
    await loadL3()
  } catch (err: any) { ElMessage.error(err?.message || '操作失败') }
}

function runBasketPreflight() {
  jobsStore.runAction('preflight', `组合预检 (${selectedRows.value.length} 只)`, { symbols: selectedRows.value.map(r => r.symbol) })
}

function inspectCandidate(row: any) { drawer.openEvidence({ title: `${row.symbol} L3 归因与证据`, raw: row }) }
watch(() => [ctx.tradingDate, ctx.horizon, ctx.previewDemo, ctx.refreshTick], loadL3)
onMounted(loadL3)
</script>
