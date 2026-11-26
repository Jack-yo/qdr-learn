<template>
  <div v-loading="loading">
    <div class="page-header">
      <h1 class="page-title">统一数据与准入中心</h1>
      <el-button type="primary" @click="jobsStore.runAction('maintenance', '全量维护与准入复检')">全量准入复检</el-button>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="数据仓库与同步" name="warehouse">
          <el-table :data="sources" stripe>
            <el-table-column prop="name" label="数据源" min-width="190" />
            <el-table-column prop="latest_date" label="最新交易日" width="125" />
            <el-table-column label="覆盖率" width="165">
              <template #default="{ row }"><el-progress :percentage="Number(row.coverage_pct ?? 100)" :status="Number(row.coverage_pct ?? 100) >= 99 ? 'success' : 'warning'" :stroke-width="8" /></template>
            </el-table-column>
            <el-table-column prop="freshness" label="新鲜度" width="105" />
            <el-table-column label="状态" width="95">
              <template #default="{ row }"><el-tag size="small" :type="row.status === 'OK' ? 'success' : 'warning'">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="115">
              <template #default="{ row }"><el-button size="small" @click="jobsStore.runAction('sync_source', `同步 ${row.name}`, { source: row.id })">立即同步</el-button></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="PIT 证券池" name="universe">
          <el-table :data="universe" stripe>
            <el-table-column prop="symbol" label="标的" width="110" />
            <el-table-column prop="sector" label="行业" width="140" />
            <el-table-column prop="adv20" label="20日均成交额" width="130" />
            <el-table-column prop="pit_since" label="PIT 起始日" width="130" />
            <el-table-column label="可交易性" width="110">
              <template #default="{ row }"><el-tag size="small" :type="row.tradable ? 'success' : 'info'">{{ row.tradable ? '合格' : '剔除' }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="公司行为与快照" name="actions">
          <el-table :data="actions" stripe>
            <el-table-column prop="date" label="生效日" width="120" />
            <el-table-column prop="symbol" label="标的" width="100" />
            <el-table-column prop="type" label="事件类型" width="130" />
            <el-table-column prop="ratio" label="除权/分红" width="110" />
            <el-table-column prop="evidence" label="核对证据" min-width="180" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><el-tag size="small" type="success">{{ row.status }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="V4 数据包 SHA256 准入" name="audit">
          <el-table :data="catalogItems" stripe>
            <el-table-column prop="file" label="数据包文件" min-width="180" />
            <el-table-column prop="sha256" label="SHA256" min-width="240" show-overflow-tooltip />
            <el-table-column prop="pit_status" label="PIT 校验" width="150" />
            <el-table-column label="状态" width="115">
              <template #default="{ row }"><el-tag size="small" :type="row.status === 'VERIFIED' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { qdrApi } from '@/api/endpoints'
import { getDemoDataCenter } from '@/api/demoFallback'
import { useContextStore } from '@/stores/context'
import { useJobsStore } from '@/stores/jobs'

const ctx = useContextStore()
const jobsStore = useJobsStore()

const activeTab = ref('warehouse')
const loading = ref(false)
const sources = ref<any[]>([])
const universe = ref<any[]>([])
const actions = ref<any[]>([])
const catalogItems = ref<any[]>([])

async function load() {
  loading.value = true
  if (ctx.previewDemo) {
    const demo = getDemoDataCenter()
    sources.value = demo.sources; universe.value = demo.universe; actions.value = demo.actions; catalogItems.value = demo.files
    loading.value = false
    return
  }
  try {
    const [wh, cat, uni, act] = await Promise.all([
      qdrApi.getWarehouseSummary(),
      qdrApi.getDataCatalog(),
      qdrApi.getDataUniverse(ctx.tradingDate || undefined).catch(() => null),
      qdrApi.getDataActions().catch(() => null),
    ])
    sources.value = Array.isArray(wh?.sources) ? wh.sources : []
    catalogItems.value = Array.isArray(wh?.datasets) ? wh.datasets : Array.isArray(cat?.datasets) ? cat.datasets : Array.isArray(cat?.files) ? cat.files : Array.isArray(cat?.items) ? cat.items : []
    universe.value = Array.isArray(uni?.symbols) ? uni.symbols : Array.isArray(uni?.items) ? uni.items : []
    actions.value = Array.isArray(act?.actions) ? act.actions : Array.isArray(act?.items) ? act.items : []
  } catch {
    sources.value = []; universe.value = []; actions.value = []; catalogItems.value = []
  } finally {
    loading.value = false
  }
}

watch(() => [ctx.tradingDate, ctx.previewDemo, ctx.refreshTick], load)
onMounted(load)
</script>
