<template>
  <section class="page" data-module="road-detail">
    <header class="page-head">
      <div>
        <h2>道路设施详情</h2>
        <p class="page-desc">查看设施基础信息、当前状态与历次处理记录，并可在当前状态允许的范围内继续流转。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/road">返回清单</RouterLink>
      </div>
    </header>

    <div v-if="errorMessage" class="detail-error">
      <p class="error-text">{{ errorMessage }}</p>
      <RouterLink class="link" to="/road">回到道路设施清单</RouterLink>
    </div>

    <template v-else-if="entry">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">当前状态</span>
          <strong class="stat-value">{{ entry.status }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">可执行动作</span>
          <strong class="stat-value">{{ allowedActions.length ? allowedActions.join('、') : '无（已到终态）' }}</strong>
        </article>
      </div>

      <div v-if="successMessage" class="banner success-text">{{ successMessage }}</div>
      <div v-if="actionError" class="banner error-text">{{ actionError }}</div>

      <table class="data-table detail-table">
        <tbody>
          <tr v-for="field in fields" :key="field">
            <th>{{ field }}</th>
            <td>{{ entry[field] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>

      <div class="action-bar">
        <button
          v-for="action in allowedActions"
          :key="action"
          class="btn primary"
          type="button"
          :disabled="busy"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
        <span v-if="!allowedActions.length" class="muted-text">该设施已封闭施工，没有可继续执行的动作。</span>
      </div>

      <h3 class="section-title">处理记录</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>动作</th>
            <th>动作前状态</th>
            <th>动作后状态</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in history" :key="index">
            <td>{{ item.time ?? '—' }}</td>
            <td>{{ item.action ?? '—' }}</td>
            <td>{{ item.from_status ?? '—' }}</td>
            <td>{{ item.to_status ?? '—' }}</td>
            <td>{{ item.remark || '—' }}</td>
          </tr>
          <tr v-if="!history.length">
            <td colspan="5" class="empty-state">暂无处理记录</td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type HistoryItem = {
  time?: string
  action?: string
  from_status?: string | null
  to_status?: string
  remark?: string
}
type Entry = Record<string, string | number | HistoryItem[] | null>

const route = useRoute()
const ENDPOINT = '/api/road'
const fields = ["设施编码", "道路名称", "道路等级", "起止桩号", "路面结构", "管养单位", "建成年份", "设施状态"]
// 与后端状态机保持一致：只有当前状态对应的那一个动作可以点
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待移交': ['办理移交'],
  '正常养护': ['标记观测'],
  '重点观测': ['封闭设施'],
  '封闭施工': [],
}

const entry = ref<Entry | null>(null)
const errorMessage = ref('')
const actionError = ref('')
const successMessage = ref('')
const busy = ref(false)

const entryId = computed(() => String(route.params.id))
const allowedActions = computed(() => ACTIONS_BY_STATUS[String(entry.value?.status ?? '')] ?? [])
const history = computed<HistoryItem[]>(() => {
  const value = entry.value?.history
  return Array.isArray(value) ? (value as HistoryItem[]) : []
})

async function runAction(action: string) {
  actionError.value = ''
  successMessage.value = ''
  busy.value = true
  try {
    const response = await request(`${ENDPOINT}/${entryId.value}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload || payload.ok === false) {
      // 被拒绝的动作：直接展示后端给出的原因（当前状态一头不允许，或已处理过）
      actionError.value = payload?.message || '道路设施动作未生效，请稍后重试'
      return
    }
    successMessage.value = payload.message || `道路设施已${action}`
    // 详情页整页（含处理记录）重新拉取
    await loadEntry()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '道路设施操作失败'
  } finally {
    busy.value = false
  }
}

async function loadEntry() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${entryId.value}`)
    if (response.status === 404) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null
      throw new Error(payload?.detail || '道路设施不存在或已归档')
    }
    if (!response.ok) {
      throw new Error('道路设施详情读取失败')
    }
    entry.value = (await response.json()) as Entry
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路设施详情读取失败'
  }
}

onMounted(loadEntry)
</script>

<style scoped>
.detail-error {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
}
.detail-table th { width: 160px; }
.action-bar { display: flex; gap: 8px; align-items: center; margin: 12px 0; }
.section-title { font-size: 15px; margin: 18px 0 8px; }
.banner { padding: 8px 12px; border-radius: 6px; background: #fff; border: 1px solid var(--border); font-size: 13px; }
.muted-text { color: var(--muted); font-size: 13px; }
.success-text { color: #157347; }
</style>
