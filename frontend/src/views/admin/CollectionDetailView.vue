<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConfirmDialog from '../../components/ConfirmDialog.vue'
import CommandSnippet from '../../components/CommandSnippet.vue'
import SiteHeader from '../../components/SiteHeader.vue'
import { authState, deleteCollection, fetchWorkspaceCollection, getCollectionScopeLabel } from '../../services/api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const deleting = ref(false)
const error = ref('')
const collection = ref(null)
const deleteDialogOpen = ref(false)

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

async function loadCollection(slug) {
  if (!slug) {
    return
  }
  loading.value = true
  error.value = ''
  try {
    collection.value = await fetchWorkspaceCollection(slug)
  } catch (err) {
    error.value = err.message
    collection.value = null
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    loading.value = false
  }
}

function handleDelete() {
  if (!collection.value || collection.value.is_deleted) {
    return
  }
  deleteDialogOpen.value = true
}

async function confirmDelete() {
  if (!collection.value || collection.value.is_deleted) {
    return
  }
  deleting.value = true
  error.value = ''
  try {
    await deleteCollection(collection.value.slug)
    router.push('/workspace?tab=collections')
  } catch (err) {
    error.value = err.message
  } finally {
    deleting.value = false
  }
}

watch(
  () => route.params.slug,
  (slug) => {
    loadCollection(typeof slug === 'string' ? slug : '')
  },
  { immediate: true },
)
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--narrow">
      <section v-if="loading" class="feedback">正在加载 Skill 集合详情...</section>
      <section v-else-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="collection" class="detail-panel">
        <div class="detail-panel__header">
          <div>
            <h1>{{ collection.name }}</h1>
            <span class="detail-modal__summary">{{ collection.slug }} · 版本 {{ collection.current_version }}</span>
          </div>
          <div class="admin-toolbar__actions admin-detail__actions">
            <router-link class="button button--ghost" to="/workspace?tab=collections">返回列表</router-link>
            <router-link
              v-if="!collection.is_deleted"
              class="button button--ghost"
              :to="`/workspace/collections/${collection.slug}/edit`"
            >
              编辑
            </router-link>
            <button
              v-if="!collection.is_deleted"
              class="button button--danger"
              type="button"
              :disabled="deleting"
              @click="handleDelete"
            >
              {{ deleting ? '删除中...' : '删除' }}
            </button>
          </div>
        </div>

        <section v-if="collection.is_deleted" class="feedback">
          当前 Skill 集合已被逻辑删除，仅管理员可查看删除状态。
        </section>

        <div class="detail-meta">
          <div class="detail-meta__item">
            <span>版本信息</span>
            <code>{{ collection.current_version }}</code>
            <small>创建于 {{ formatDate(collection.created_at) }}，最近更新 {{ formatDate(collection.updated_at) }}</small>
          </div>
          <div class="detail-meta__item">
            <span>Skill 条目</span>
            <code>{{ collection.item_count }}</code>
            <small>来自 Skill 集合 ZIP 根目录一级 Skill 目录。</small>
          </div>
          <div class="detail-meta__item">
            <span>可见范围</span>
            <code>{{ getCollectionScopeLabel(collection) }}</code>
            <small>
              {{
                collection.scope_type === 'GROUP'
                  ? '仅该组成员和管理员可查看'
                  : collection.scope_type === 'ORGANIZATION'
                    ? '仅该组织及其子组织成员和管理员可查看'
                    : '所有访客都可查看'
              }}
            </small>
          </div>
          <div v-if="isAdmin" class="detail-meta__item">
            <span>归属用户</span>
            <code>{{ collection.owner_username || '-' }}</code>
            <small>{{ collection.is_deleted ? `删除时间 ${formatDate(collection.deleted_at)}` : '当前状态正常' }}</small>
          </div>
          <CommandSnippet label="Skill 集合安装" :command="collection.install_command" />
        </div>

        <section class="collection-items-panel">
          <div class="registry-panel__header">
            <h2>Skill 集合清单</h2>
            <p>{{ collection.preview_items.length }} 个 Skill，checksum 来自规范化文件清单。</p>
          </div>
          <ul class="collection-items-list">
            <li v-for="item in collection.preview_items" :key="item.path">
              <strong>{{ item.name }}</strong>
              <span>{{ item.file_count }} 个文件</span>
              <code>{{ item.sha256 }}</code>
            </li>
          </ul>
        </section>

        <section v-if="collection.version_history?.length" class="collection-items-panel">
          <div class="registry-panel__header">
            <h2>版本历史</h2>
            <p>{{ collection.version_history.length }} 个快照。</p>
          </div>
          <ul class="collection-version-list">
            <li v-for="version in collection.version_history" :key="version.version">
              <span class="version-chip">{{ version.version }}</span>
              <strong>{{ version.item_count }} 个 Skill</strong>
              <small>{{ formatDate(version.created_at) }}</small>
            </li>
          </ul>
        </section>

        <article class="markdown-body detail-modal__body" v-html="collection.description_html"></article>
      </section>
    </main>
    <ConfirmDialog
      :open="deleteDialogOpen"
      title="删除 Skill 集合"
      :summary="collection ? `目标：${collection.name}` : ''"
      confirm-label="确认删除"
      :busy="deleting"
      @close="deleteDialogOpen = false"
      @confirm="confirmDelete"
    />
  </div>
</template>
