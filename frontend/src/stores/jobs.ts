import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { qdrApi } from '@/api/endpoints'

export interface JobRecord {
  id: string; action: string; status: string; started_at?: string; message?: string; logs?: string[]
}

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobRecord[]>([])
  const loading = ref(false)
  let pollTimer: number | null = null

  async function fetchJobs() {
    try {
      const res = await qdrApi.getCurrentJobs()
      if (Array.isArray(res?.jobs)) jobs.value = res.jobs
      else if (res?.job) jobs.value = [res.job]
    } catch {}
  }

  async function runAction(action: string, label: string, payload?: Record<string, unknown>) {
    loading.value = true
    try {
      const res = await qdrApi.runAction(action, payload)
      ElMessage.success(`已提交：${label}`)
      jobs.value.unshift({
        id: res?.job_id || `local-${Date.now()}`,
        action: label,
        status: res?.status || 'RUNNING',
        started_at: new Date().toLocaleTimeString(),
        message: res?.message || '已入队',
      })
      startPolling()
    } catch (err: any) {
      ElMessage.error(`提交失败：${err?.message || '后端未启动'}`)
    } finally {
      loading.value = false
    }
  }

  function startPolling() {
    if (pollTimer !== null) return
    pollTimer = window.setInterval(async () => {
      await fetchJobs()
      const hasRunning = jobs.value.some(j => j.status === 'RUNNING' || j.status === 'PENDING')
      if (!hasRunning && pollTimer !== null) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    }, 3000)
  }

  return { jobs, loading, fetchJobs, runAction, startPolling }
})
