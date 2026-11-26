import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Horizon } from '@/api/endpoints'

export type ColorMode = 'us' | 'cn'

export const useContextStore = defineStore('context', () => {
  const tradingDate = ref<string>('')
  const horizon = ref<Horizon>('H3')
  const colorMode = ref<ColorMode>('us')
  const previewDemo = ref<boolean>(false)
  const refreshTick = ref<number>(0)

  function toggleColorMode() {
    colorMode.value = colorMode.value === 'us' ? 'cn' : 'us'
  }
  function triggerRefresh() {
    refreshTick.value += 1
  }

  return { tradingDate, horizon, colorMode, previewDemo, refreshTick, toggleColorMode, triggerRefresh }
})
