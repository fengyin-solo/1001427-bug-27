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
        <input v-model="filters.grade" placeholder="按道路等级检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
          <th>明细</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-for="action in actionsFor(row)" :key="action">
              <button
                v-if="!busyIds.has(String(row.id))"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-if="!actionsFor(row).length" class="muted-text">—</span>
          </td>
          <td>
            <RouterLink class="link" :to="`/road/${row.id}`">查看详情</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的道路设施数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条道路设施记录</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/road'
const columns = ["设施编码", "道路名称", "道路等级", "起止桩号", "路面结构", "管养单位", "建成年份", "设施状态"]
// 状态机在前端的镜像：每种当前状态只暴露允许执行的那一个动作
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待移交': ['办理移交'],
  '正常养护': ['标记观测'],
  '重点观测': ['封闭设施'],
  '封闭施工': [],
}
const stats = reactive([
  { label: '在养道路', value: 0 },
  { label: '重点观测道路', value: 0 },
  { label: '管养里程（公里）', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = reactive({ code: '', name: '', grade: '' })
const busyIds = ref<Set<string>>(new Set())

function actionsFor(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function resetFilters() {
  filters.code = ''
  filters.name = ''
  filters.grade = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '道路设施登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  const rowId = String(row.id)
  busyIds.value.add(rowId)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    // 动作被业务规则拒绝时后端仍返回 200 + ok:false，必须读回执正文，
    // 不能只看 HTTP 状态，否则会把“没做成”提示成“操作成功”。
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload || payload.ok === false) {
      errorMessage.value = payload?.message || '道路设施动作未生效，请稍后重试'
      return
    }
    successMessage.value = payload.message || `道路设施已${action}`
    // 动作生效后，列表与统计概要同时刷新
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路设施操作失败'
  } finally {
    busyIds.value.delete(rowId)
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = await response.json() as Record<string, number>
    stats[0].value = Number(payload.maintained ?? 0)
    stats[1].value = Number(payload.watching ?? 0)
    stats[2].value = Number(payload.mileage ?? 0)
  } catch {
    // 统计读不到不阻断列表使用
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.code.trim()) params.set('code', filters.code.trim())
  if (filters.name.trim()) params.set('name', filters.name.trim())
  if (filters.grade.trim()) params.set('grade', filters.grade.trim())
  const query = params.toString()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
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

<style scoped>
.muted-text { color: var(--muted); }
.success-text { color: #157347; }
</style>
