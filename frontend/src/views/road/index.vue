<template>
  <section class="page" data-module="road">
    <header class="page-head">
      <div>
        <h2>道路设施管理</h2>
        <p class="page-desc">维护道路设施，围绕设施编码、道路名称、道路等级、起止桩号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记道路设施</button>
        <button class="btn" type="button" @click="exportRows">导出道路设施清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>设施编码</span>
        <input v-model="filters.code" placeholder="按设施编码检索" />
      </label>
      <label class="filter-item">
        <span>道路名称</span>
        <input v-model="filters.name" placeholder="按道路名称检索" />
      </label>
      <label class="filter-item">
        <span>道路等级</span>
        <input v-model="filters.level" placeholder="按道路等级检索" />
      </label>
      <label class="filter-item">
        <span>设施状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="busy || !actionAllowed(action, row)"
              :title="actionHint(action, row)"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无道路设施数据，可先登记道路设施</td>
        </tr>
      </tbody>
    </table>

    <aside v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>道路设施详情 #{{ detail.id }}</h3>
        <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
      </header>
      <dl class="detail-grid">
        <template v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>{{ detail[column] ?? '—' }}</dd>
        </template>
      </dl>
    </aside>

    <footer class="page-foot">
      <span>共 {{ total }} 条道路设施记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number }
type ActionResult = { ok: boolean; message?: string; detail?: string }

const ENDPOINT = '/api/road'
const columns = ["设施编码", "道路名称", "道路等级", "起止桩号", "路面结构", "管养单位", "建成年份", "设施状态"]
const statuses = ["待移交", "正常养护", "重点观测", "封闭施工"]
// 与后端状态机同一口径：每个动作只在特定现状下允许执行
const actionFlow: Record<string, { from: string[] }> = {
  '办理移交': { from: ['待移交'] },
  '标记观测': { from: ['正常养护'] },
  '封闭设施': { from: ['重点观测'] },
}
const actions = Object.keys(actionFlow)

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '在养道路', value: 0 },
  { label: '重点观测道路', value: 0 },
  { label: '管养里程', value: 0 },
])
const detail = ref<Row | null>(null)
const busy = ref(false)
const noticeMessage = ref('')
const errorMessage = ref('')
const filters = ref({ code: '', name: '', level: '', status: '' })

function actionAllowed(action: string, row: Row) {
  return actionFlow[action]?.from.includes(String(row.status ?? '')) ?? false
}

function actionHint(action: string, row: Row) {
  if (actionAllowed(action, row)) {
    return `对 #${String(row.id)} 执行${action}`
  }
  const expect = actionFlow[action]?.from.join('、') ?? ''
  return `当前状态「${String(row.status ?? '—')}」不允许执行，仅「${expect}」状态可${action}`
}

function resetFilters() {
  filters.value = { code: '', name: '', level: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '道路设施登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (busy.value) {
    return
  }
  busy.value = true
  noticeMessage.value = ''
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as ActionResult | null
    if (!response.ok || !payload?.ok) {
      // 被拦下的动作要讲清是哪一头不允许：动作本身、当前状态，还是记录不存在
      errorMessage.value = payload?.message ?? payload?.detail ?? `道路设施动作未生效（接口返回 ${response.status}）`
      return
    }
    noticeMessage.value = payload.message ?? `道路设施已${action}`
    // 动作办完后列表、详情与统计概要一起刷新，回执与清单保持同一口径
    await Promise.all([reload(), reloadStats(), reloadDetail()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路设施操作失败'
  } finally {
    busy.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error(`道路设施 ${String(row.id)} 明细读取失败`)
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路设施明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reloadDetail() {
  if (detail.value?.id == null) {
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${detail.value.id}`)
    if (response.ok) {
      detail.value = (await response.json()) as Row
    }
  } catch {
    // 详情刷新失败不打断列表与统计概要的更新
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as { cards?: StatCard[] }
    if (payload.cards) {
      stats.value = payload.cards
    }
  } catch {
    // 统计概要刷新失败时保留旧值，等下一次动作后再拉
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  const code = filters.value.code.trim()
  const name = filters.value.name.trim()
  const level = filters.value.level.trim()
  if (code) {
    params.set('keyword', code)
  }
  if (name) {
    params.set('name', name)
  }
  if (level) {
    params.set('level', level)
  }
  if (filters.value.status) {
    params.set('status', filters.value.status)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('道路设施列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路设施列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
