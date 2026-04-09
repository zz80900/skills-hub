<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { authState, fetchWorkspaceSkills } from '../../services/api'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const search = ref('')
const skills = ref([])
let searchTimer = null

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const pageEyebrow = computed(() => (isAdmin.value ? '工作台' : '我的 Skill'))
const pageTitle = computed(() => (isAdmin.value ? 'Skill 总览' : '我上传的 Skill'))
const searchHint = computed(() =>
  search.value
    ? `当前关键词：${search.value}`
    : isAdmin.value
      ? '管理员可搜索全部 Skill，并查看逻辑删除状态。'
      : '按名称或描述搜索你自己的 Skill。',
)

const resultSummary = computed(() => {
  if (loading.value) {
    return '正在同步数据...'
  }
  if (search.value) {
    return `当前匹配 ${skills.value.length} 条记录`
  }
  return isAdmin.value
    ? `当前共 ${skills.value.length} 条 Skill 记录`
    : `当前共 ${skills.value.length} 个我的 Skill`
})

const emptyStateText = computed(() => {
  if (search.value) {
    return `没有找到与“${search.value}”匹配的 Skill。`
  }
  return isAdmin.value ? '当前还没有 Skill 记录。' : '你还没有上传 Skill。'
})

function formatDate(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function loadSkills(keyword = '') {
  loading.value = true
  error.value = ''
  try {
    skills.value = await fetchWorkspaceSkills(keyword)
  } catch (err) {
    error.value = err.message
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    loading.value = false
  }
}

watch(search, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    loadSkills(value.trim())
  }, 250)
})

onMounted(() => {
  loadSkills()
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
})

function clearSearch() {
  if (!search.value) {
    return
  }
  search.value = ''
}
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content">
      <section class="admin-toolbar">
        <div class="admin-toolbar__intro">
          <p class="eyebrow">{{ pageEyebrow }}</p>
          <h1>{{ pageTitle }}</h1>
          <p class="admin-toolbar__summary">{{ resultSummary }}</p>
        </div>
        <div class="admin-toolbar__actions">
          <router-link class="button" to="/workspace/skills/new">新增 Skill</router-link>
          <router-link v-if="isAdmin" class="button button--ghost" to="/workspace/users">用户管理</router-link>
        </div>
      </section>

      <section class="search-panel admin-search">
        <div class="admin-search__copy">
          <p class="eyebrow">快速筛选</p>
          <h2>{{ isAdmin ? '检索全部 Skill' : '检索我的 Skill' }}</h2>
          <p class="search-panel__lead">
            {{ isAdmin ? '管理员列表包含全部 Skill，并展示归属人和逻辑删除状态。' : '你只能看到并操作自己上传的 Skill。' }}
          </p>
        </div>
        <label class="search-field search-field--admin" for="workspace-skill-search">
          <div class="search-field__meta">
            <span class="search-field__label">{{ searchHint }}</span>
            <span class="search-field__status">{{ loading ? '检索中' : `${skills.length} 条结果` }}</span>
          </div>
          <div class="search-field__control">
            <span class="search-field__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" role="presentation">
                <path
                  d="M10.5 4.75a5.75 5.75 0 1 0 0 11.5a5.75 5.75 0 0 0 0-11.5Zm0-1.5a7.25 7.25 0 1 1 4.544 12.9l4.028 4.027a.75.75 0 0 1-1.06 1.061l-4.028-4.028A7.25 7.25 0 0 1 10.5 3.25Z"
                  fill="currentColor"
                />
              </svg>
            </span>
            <input
              id="workspace-skill-search"
              v-model.trim="search"
              class="text-input"
              type="search"
              placeholder="搜索名称、描述或用途关键词"
            />
            <button
              v-if="search"
              class="search-field__clear"
              type="button"
              @click="clearSearch"
            >
              清空
            </button>
          </div>
        </label>
      </section>

      <section v-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="loading" class="feedback">正在加载 Skill 列表...</section>
      <section v-else-if="!skills.length" class="feedback">{{ emptyStateText }}</section>

      <section v-else class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr>
              <th scope="col">标题</th>
              <th v-if="isAdmin" scope="col">归属用户</th>
              <th scope="col">当前版本</th>
              <th scope="col">上传者</th>
              <th v-if="isAdmin" scope="col">状态</th>
              <th scope="col">更新时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="skill in skills" :key="skill.id" :class="{ 'admin-table__row--deleted': skill.is_deleted }">
              <td>
                <router-link class="admin-table__title" :to="`/workspace/skills/${skill.name}`">
                  {{ skill.name }}
                </router-link>
              </td>
              <td v-if="isAdmin">{{ skill.owner_username || '-' }}</td>
              <td>
                <span class="version-chip">{{ skill.current_version }}</span>
              </td>
              <td>{{ skill.contributor || '-' }}</td>
              <td v-if="isAdmin">
                <span class="status-chip" :class="{ 'status-chip--deleted': skill.is_deleted }">
                  {{ skill.is_deleted ? '已删除' : '正常' }}
                </span>
              </td>
              <td>{{ formatDate(skill.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>
</template>
