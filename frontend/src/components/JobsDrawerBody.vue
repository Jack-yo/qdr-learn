<template>
  <div class="jobs-wrap">
    <el-empty v-if="!jobsStore.jobs.length" description="暂无后台任务" :image-size="56" />
    <el-card v-for="job in jobsStore.jobs" :key="job.id" shadow="never">
      <div class="job-head">
        <strong>{{ job.action }}</strong>
        <el-tag :type="job.status === 'DONE' ? 'success' : job.status === 'FAILED' ? 'danger' : 'primary'" size="small">{{ job.status }}</el-tag>
      </div>
      <div class="job-meta">{{ job.started_at || '' }} · {{ job.message || '' }}</div>
      <pre v-if="job.logs?.length" class="job-log">{{ job.logs.join('\\n') }}</pre>
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted } from 'vue'
import { useJobsStore } from '@/stores/jobs'
const jobsStore = useJobsStore()
onMounted(() => jobsStore.fetchJobs())
</script>
<style scoped>
.jobs-wrap { display: flex; flex-direction: column; gap: 10px; }
.job-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.job-meta { font-size: 12px; color: #6b7280; }
.job-log { margin: 8px 0 0; padding: 8px; background: #111827; color: #e5e7eb; border-radius: 4px; font-size: 11px; max-height: 160px; overflow: auto; }
</style>
