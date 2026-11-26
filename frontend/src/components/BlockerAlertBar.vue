<template>
  <el-alert v-if="title" :title="title" type="error" :description="detail" show-icon :closable="false" style="margin-bottom: 14px">
    <template #default>
      <div style="margin-top: 8px; display: flex; gap: 8px">
        <el-button type="warning" size="small" @click="$emit('fix')">一键补数并复检</el-button>
        <el-button size="small" @click="$emit('goto-data')">数据中心</el-button>
      </div>
    </template>
  </el-alert>
</template>
<script setup lang="ts">
defineProps<{ title?: string; detail?: string }>()
defineEmits<{ (e: 'fix'): void; (e: 'goto-data'): void }>()
</script>
