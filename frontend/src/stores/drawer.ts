import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface DrawerKV { label: string; value: string; mono?: boolean }
export type DrawerKind = 'evidence' | 'jobs'

export const useDrawerStore = defineStore('drawer', () => {
  const visible = ref(false)
  const kind = ref<DrawerKind>('evidence')
  const title = ref('')
  const subtitle = ref('')
  const items = ref<DrawerKV[]>([])
  const rawJson = ref<unknown>(null)

  function openEvidence(opts: { title: string; subtitle?: string; items?: DrawerKV[]; raw?: unknown }) {
    kind.value = 'evidence'
    title.value = opts.title
    subtitle.value = opts.subtitle || ''
    items.value = opts.items || []
    rawJson.value = opts.raw ?? null
    visible.value = true
  }

  function openJobs() {
    kind.value = 'jobs'
    title.value = '后台任务与日志'
    subtitle.value = 'POST /api/run/<action>'
    visible.value = true
  }

  function close() { visible.value = false }
  return { visible, kind, title, subtitle, items, rawJson, openEvidence, openJobs, close }
})
