<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CommandSnippet from '../../components/CommandSnippet.vue'
import SiteHeader from '../../components/SiteHeader.vue'
import { deleteSkill, fetchAdminSkill } from '../../services/api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const deleting = ref(false)
const error = ref('')
const skill = ref(null)

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
    skill.value = await fetchAdminSkill(name)
  } catch (err) {
    error.value = err.message
    skill.value = null
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  if (!skill.value) {
    return
  }
  if (!window.confirm(`确认删除 Skill「${skill.value.name}」吗？删除后前台与后台列表都将隐藏该 Skill。`)) {
    return
  }

  deleting.value = true
  error.value = ''
  try {
    await deleteSkill(skill.value.name)
    router.push('/admin')
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
            <p class="eyebrow">管理后台</p>
            <h1>{{ skill.name }}</h1>
            <p class="detail-modal__summary">当前版本 {{ skill.current_version }}</p>
          </div>
          <div class="admin-toolbar__actions">
            <router-link class="button button--ghost" :to="`/admin/skills/${skill.name}/edit`">编辑</router-link>
            <button class="button button--danger" type="button" :disabled="deleting" @click="handleDelete">
              {{ deleting ? '删除中...' : '删除' }}
            </button>
          </div>
        </div>

        <div class="detail-meta">
          <div class="detail-meta__item">
            <span>版本信息</span>
            <code>{{ skill.current_version }}</code>
            <small>创建于 {{ formatDate(skill.created_at) }}，最近更新 {{ formatDate(skill.updated_at) }}</small>
          </div>
          <div class="detail-meta__item">
            <span>贡献者</span>
            <code>{{ skill.contributor || '未填写' }}</code>
          </div>
          <CommandSnippet label="Skill 安装" :command="skill.install_command" />
        </div>

        <section class="admin-history">
          <div class="admin-history__header">
            <h2>版本历史</h2>
            <p>每次保存都会生成新的版本快照。</p>
          </div>
          <table class="admin-table admin-table--history">
            <thead>
              <tr>
                <th scope="col">版本号</th>
                <th scope="col">贡献者</th>
                <th scope="col">生成时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in skill.version_history" :key="item.version">
                <td>
                  <span class="version-chip" :class="{ 'is-current': item.version === skill.current_version }">
                    {{ item.version }}
                  </span>
                </td>
                <td>{{ item.contributor || '-' }}</td>
                <td>{{ formatDate(item.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <article class="markdown-body detail-modal__body" v-html="skill.description_html"></article>
      </section>
    </main>
  </div>
</template>
