<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { clearToken, fetchAdminSkills, logout } from '../../services/api'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const search = ref('')
const skills = ref([])
let searchTimer = null

const searchHint = computed(() =>
  search.value
    ? `当前关键词：${search.value}`
    : '按 Skill 名称或描述检索，输入后自动刷新列表。',
)

const resultSummary = computed(() => {
  if (loading.value) {
    return '正在同步后台数据...'
  }

  return search.value
    ? `当前匹配 ${skills.value.length} 个结果`
    : `当前共 ${skills.value.length} 个 Skill`
})

const emptyStateText = computed(() =>
  search.value
    ? `没有找到与“${search.value}”匹配的 Skill，请尝试更换关键词。`
    : '当前还没有 Skill。',
)

async function loadSkills(keyword = '') {
  loading.value = true
  error.value = ''
  try {
    skills.value = await fetchAdminSkills(keyword)
  } catch (err) {
    error.value = err.message
    if (err.message.includes('登录')) {
      clearToken()
      router.push('/admin/login')
    }
  } finally {
    loading.value = false
  }
}

async function handleLogout() {
  try {
    await logout()
  } finally {
    clearToken()
    router.push('/admin/login')
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
          <p class="eyebrow">管理后台</p>
          <h1>Skills 管理</h1>
          <p class="admin-toolbar__summary">{{ resultSummary }}</p>
        </div>
        <div class="admin-toolbar__actions">
          <router-link class="button" to="/admin/skills/new">新增 Skill</router-link>
          <button class="button button--ghost" type="button" @click="handleLogout">退出登录</button>
        </div>
      </section>

      <section class="search-panel admin-search">
        <div class="admin-search__copy">
          <p class="eyebrow">快速筛选</p>
          <h2>搜索 Skill</h2>
          <p class="search-panel__lead">搜索区改为稳定的后台工具栏，避免输入框样式和布局在不同宽度下错位。</p>
        </div>
        <label class="search-field search-field--admin" for="admin-skill-search">
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
              id="admin-skill-search"
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
      <section v-else-if="loading" class="feedback">正在加载后台数据...</section>
      <section v-else-if="!skills.length" class="feedback">{{ emptyStateText }}</section>

      <section v-else class="admin-list">
        <article v-for="skill in skills" :key="skill.name" class="admin-list__item">
          <div>
            <h2>{{ skill.name }}</h2>
            <p v-if="skill.contributor" class="admin-list__meta">贡献者：{{ skill.contributor }}</p>
            <div class="admin-list__description" v-html="skill.description_html"></div>
          </div>
          <div class="admin-list__actions">
            <code>{{ skill.install_command }}</code>
            <router-link class="button button--ghost" :to="`/admin/skills/${skill.name}/edit`">
              编辑 / 升级
            </router-link>
          </div>
        </article>
      </section>
    </main>
  </div>
</template>
