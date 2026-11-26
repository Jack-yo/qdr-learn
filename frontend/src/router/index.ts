import { createRouter, createWebHashHistory } from 'vue-router'
import OverviewView from '@/views/OverviewView.vue'
import L1MarketView from '@/views/L1MarketView.vue'
import L2StyleView from '@/views/L2StyleView.vue'
import L3AlphaView from '@/views/L3AlphaView.vue'
import L4RiskView from '@/views/L4RiskView.vue'
import DataCenterView from '@/views/DataCenterView.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', component: OverviewView },
    { path: '/l1', name: 'l1', component: L1MarketView },
    { path: '/l2', name: 'l2', component: L2StyleView },
    { path: '/l3', name: 'l3', component: L3AlphaView },
    { path: '/l4', name: 'l4', component: L4RiskView },
    { path: '/data', name: 'data', component: DataCenterView },
    { path: '/market', redirect: '/l1' },
    { path: '/styles', redirect: '/l2' },
    { path: '/factors', redirect: { path: '/l3', query: { tab: 'lab' } } },
    { path: '/strategies', redirect: { path: '/l3', query: { tab: 'strategy' } } },
    { path: '/backtests', redirect: { path: '/l3', query: { tab: 'strategy' } } },
    { path: '/signals', redirect: { path: '/l3', query: { tab: 'signals' } } },
    { path: '/paper', redirect: '/l4' },
    { path: '/warehouse', redirect: '/data' },
  ],
})
