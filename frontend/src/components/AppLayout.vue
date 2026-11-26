<template>
  <el-container class="app-shell">
    <el-header class="app-header" height="54px">
      <div class="header-left">
        <div class="brand">
          <span class="brand-badge">QDR</span>
          <span class="brand-title">Quant Studio V4</span>
        </div>
        <el-divider direction="vertical" />
        <el-date-picker v-model="ctx.tradingDate" type="date" value-format="YYYY-MM-DD" placeholder="交易日 T" size="small" style="width: 138px" clearable />
        <el-radio-group v-model="ctx.horizon" size="small">
          <el-radio-button value="H1">H1</el-radio-button>
          <el-radio-button value="H3">H3</el-radio-button>
          <el-radio-button value="H5">H5</el-radio-button>
        </el-radio-group>
      </div>

      <div class="header-right">
        <el-switch v-model="ctx.previewDemo" size="small" inline-prompt active-text="样例" inactive-text="实盘" />
        <el-button size="small" @click="ctx.toggleColorMode()">
          <span :style="{ color: ctx.colorMode === 'us' ? '#16a34a' : '#dc2626', fontWeight: 600 }">
            {{ ctx.colorMode === 'us' ? '绿涨红跌' : '红涨绿跌' }}
          </span>
        </el-button>
        <el-button size="small" @click="ctx.triggerRefresh()">刷新</el-button>
        <el-badge :value="runningCount" :hidden="runningCount === 0" type="warning">
          <el-button size="small" @click="drawer.openJobs()">任务</el-button>
        </el-badge>
        <el-button type="primary" size="small" :loading="jobsStore.loading" @click="jobsStore.runAction('daily', '盘后日终研究')">
          运行日终
        </el-button>
      </div>
    </el-header>

    <el-container class="app-body">
      <el-aside width="200px" class="app-aside">
        <el-menu :default-active="activeRoute" router class="side-menu">
          <el-menu-item index="/overview"><el-icon><Odometer /></el-icon><span>总览</span></el-menu-item>
          <el-menu-item index="/l1"><el-icon><TrendCharts /></el-icon><span>L1 市场状态</span></el-menu-item>
          <el-menu-item index="/l2"><el-icon><Grid /></el-icon><span>L2 经典风格</span></el-menu-item>
          <el-menu-item index="/l3"><el-icon><DataAnalysis /></el-icon><span>L3 个股 Alpha</span></el-menu-item>
          <el-menu-item index="/l4"><el-icon><Lock /></el-icon><span>L4 持仓风控</span></el-menu-item>
          <el-menu-item index="/data"><el-icon><Coin /></el-icon><span>数据中心</span></el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <el-drawer v-model="drawer.visible" :title="drawer.title" size="460px" destroy-on-close>
      <div v-if="drawer.subtitle" class="drawer-sub">{{ drawer.subtitle }}</div>
      <JobsDrawerBody v-if="drawer.kind === 'jobs'" />
      <template v-else>
        <el-descriptions :column="1" border size="small" v-if="drawer.items.length">
          <el-descriptions-item v-for="item in drawer.items" :key="item.label" :label="item.label">
            <span :class="{ 'mono-val': item.mono }">{{ item.value }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <pre v-if="drawer.rawJson" class="raw-json">{{ JSON.stringify(drawer.rawJson, null, 2) }}</pre>
      </template>
    </el-drawer>
  </el-container>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Odometer, TrendCharts, Grid, DataAnalysis, Lock, Coin } from '@element-plus/icons-vue'
import { useContextStore } from '@/stores/context'
import { useDrawerStore } from '@/stores/drawer'
import { useJobsStore } from '@/stores/jobs'
import JobsDrawerBody from './JobsDrawerBody.vue'

const route = useRoute()
const router = useRouter()
const ctx = useContextStore()
const drawer = useDrawerStore()
const jobsStore = useJobsStore()

const activeRoute = computed(() => route.path)
const runningCount = computed(() => jobsStore.jobs.filter(j => j.status === 'RUNNING').length)

watch(() => [ctx.tradingDate, ctx.horizon], () => {
  const query: Record<string, string> = { ...(route.query as Record<string, string>), h: ctx.horizon }
  if (ctx.tradingDate) query.date = ctx.tradingDate
  else delete query.date
  router.replace({ query }).catch(() => {})
})
</script>

<style scoped>
.app-shell { min-height: 100vh; }
.app-header {
  position: sticky; top: 0; z-index: 20; background: #fff; border-bottom: 1px solid #e4e7ed;
  display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 18px;
}
.header-left, .header-right { display: flex; align-items: center; gap: 10px; }
.brand { display: flex; align-items: center; gap: 8px; }
.brand-badge {
  width: 26px; height: 26px; border-radius: 4px; background: #409eff; color: #fff;
  font-weight: 700; font-size: 11px; display: inline-flex; align-items: center; justify-content: center;
}
.brand-title { font-size: 14px; font-weight: 600; }
.app-body { min-height: calc(100vh - 54px); }
.app-aside { background: #fff; border-right: 1px solid #e4e7ed; padding: 8px 6px; }
.side-menu { border-right: none; }
.app-main { padding: 18px 22px; max-width: 1440px; width: 100%; margin: 0 auto; }
.drawer-sub { font-size: 12px; color: #6b7280; margin-bottom: 12px; }
.mono-val { font-family: ui-monospace, monospace; font-size: 12px; }
.raw-json { margin-top: 14px; background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 4px; padding: 10px; font-size: 11px; overflow: auto; max-height: 360px; }
</style>
