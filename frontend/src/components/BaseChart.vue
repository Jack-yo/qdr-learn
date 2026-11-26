<template>
  <div class="chart-wrap" :style="{ height: height + 'px' }">
    <canvas v-if="hasData" ref="canvasRef" />
    <el-empty v-else :description="emptyText" :image-size="52" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  Chart, LineController, BarController, DoughnutController,
  LineElement, BarElement, ArcElement, PointElement,
  LinearScale, CategoryScale, Filler, Tooltip, Legend,
  type ChartConfiguration,
} from 'chart.js'

Chart.register(
  LineController, BarController, DoughnutController,
  LineElement, BarElement, ArcElement, PointElement,
  LinearScale, CategoryScale, Filler, Tooltip, Legend
)

const props = withDefaults(
  defineProps<{ config: ChartConfiguration | null; height?: number; hasData?: boolean; emptyText?: string }>(),
  { height: 240, hasData: true, emptyText: '暂无数据' }
)

const canvasRef = ref<HTMLCanvasElement | null>(null)
let instance: Chart | null = null

function destroy() {
  if (instance) { instance.destroy(); instance = null }
}

async function renderChart() {
  destroy()
  if (!props.hasData || !props.config) return
  await nextTick()
  if (!canvasRef.value) return
  instance = new Chart(canvasRef.value, {
    ...props.config,
    options: { responsive: true, maintainAspectRatio: false, ...(props.config.options || {}) },
  })
}

watch(() => [props.config, props.hasData], renderChart, { deep: true })
onMounted(renderChart)
onBeforeUnmount(destroy)
</script>

<style scoped>
.chart-wrap { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; }
</style>
