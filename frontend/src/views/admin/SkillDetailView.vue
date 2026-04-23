<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CommandSnippet from '../../components/CommandSnippet.vue'
import SiteHeader from '../../components/SiteHeader.vue'
import { authState, deleteSkill, fetchWorkspaceSkill } from '../../services/api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const deleting = ref(false)
const error = ref('')
const skill = ref(null)

const isAdmin = computed(() => authState.user?.role === 'ADMIN')

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

async function loadSkill(name) {
  if (!name) {
    return
  }
  loading.value = true
  error.value = ''
  try {
    skill.value = await fetchWorkspaceSkill(name)
  } catch (err) {
    error.value = err.message
    skill.value = null
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  if (!skill.value || skill.value.is_deleted) {
    return
  }
  if (!window.confirm(`确认删除 Skill「${skill.value.name}」吗？该操作为逻辑删除。`)) {
    return
  }

  deleting.value = true
  error.value = ''
  try {
    await deleteSkill(skill.value.name)
    router.push('/workspace')
  } catch (err) {
    error.value = err.message
  } finally {
    deleting.value = false
  }
}

watch(
  () => route.params.name,
  (name) => {
    loadSkill(typeof name === 'string' ? name : '')
  },
  { immediate: true },
)
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--narrow">
      <section v-if="loading" class="feedback">正在加载 Skill 详情...</section>
      <section v-else-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="skill" class="detail-panel">
        <div class="detail-panel__header">
          <div>
            <p class="eyebrow">{{ isAdmin ? '工作台' : '我的 Skill' }}</p>
            <h1>{{ skill.name }}</h1>
            <p class="detail-modal__summary">当前版本 {{ skill.current_version }}</p>
          </div>
          <div class="admin-toolbar__actions admin-detail__actions">
            <router-link class="button button--ghost" to="/workspace">返回列表</router-link>
            <router-link
              v-if="!skill.is_deleted"
              class="button button--ghost"
              :to="`/workspace/skills/${skill.name}/edit`"
            >
              编辑
            </router-link>
            <button
              v-if="!skill.is_deleted"
              class="button button--danger"
              type="button"
              :disabled="deleting"
              @click="handleDelete"
            >
              {{ deleting ? '删除中...' : '删除' }}
            </button>
          </div>
        </div>

        <section v-if="skill.is_deleted" class="feedback">
          当前 Skill 已被逻辑删除，仅管理员可查看删除状态。
        </section>

        <div class="detail-meta">
          <div class="detail-meta__item">
            <span>版本信息</span>
            <code>{{ skill.current_version }}</code>
            <small>创建于 {{ formatDate(skill.created_at) }}，最近更新 {{ formatDate(skill.updated_at) }}</small>
          </div>
          <div class="detail-meta__item">
            <span>上传者</span>
            <code>{{ skill.contributor || '未填写' }}</code>
          </div>
          <div class="detail-meta__item">
            <span>可见范围</span>
            <code>{{ skill.group_name ? `组内 · ${skill.group_name}` : '公开' }}</code>
            <small>{{ skill.group_name ? '仅该组成员和管理员可在首页查看' : '所有访客都可在首页查看' }}</small>
          </div>
          <div v-if="isAdmin" class="detail-meta__item">
            <span>归属用户</span>
            <code>{{ skill.owner_username || '-' }}</code>
            <small>{{ skill.is_deleted ? `删除时间 ${formatDate(skill.deleted_at)}` : '当前状态正常' }}</small>
          </div>
          <CommandSnippet label="Skill 安装" :command="skill.install_command" />
        </div>

        <article class="markdown-body detail-modal__body" v-html="skill.description_html"></article>
      </section>
    </main>
  </div>
</template>
