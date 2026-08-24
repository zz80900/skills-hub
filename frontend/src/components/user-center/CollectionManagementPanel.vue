<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import CollectionFormView from '../../views/admin/CollectionFormView.vue'
import InfoModal from '../InfoModal.vue'
import ListState from '../ListState.vue'
import { authState, fetchWorkspaceCollections, getCollectionScopeLabel } from '../../services/api'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const search = ref('')
const collections = ref([])
const isFormModalOpen = ref(false)
const editingCollectionSlug = ref('')
const formModalKey = ref(0)
let searchTimer = null
let queryId = 0

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const pageTitle = computed(() => (isAdmin.value ? '全部 Skill 集合' : '我上传的 Skill 集合'))
const resultSummary = computed(() => {
  if (loading.value) {
    return '正在同步数据...'
  }
  if (search.value) {
    return `当前匹配 ${collections.value.length} 条记录`
  }
  return isAdmin.value ? `当前共 ${collections.value.length} 条 Skill 集合记录` : `当前共 ${collections.value.length} 个我的 Skill 集合`
})
const activeCount = computed(() => collections.value.filter((item) => !item.is_deleted).length)
const deletedCount = computed(() => collections.value.filter((item) => item.is_deleted).length)
const searchHint = computed(() =>
  search.value
    ? `当前关键词：${search.value}`
    : '按名称、slug 或描述搜索 Skill 集合。',
)
const emptyStateText = computed(() => {
  if (search.value) {
    return `没有找到与“${search.value}”匹配的 Skill 集合。`
  }
  return isAdmin.value ? '当前还没有 Skill 集合记录。' : '你还没有上传 Skill 集合。'
})
const blockingError = computed(() => (!collections.value.length ? error.value : ''))
const refreshError = computed(() => (collections.value.length ? error.value : ''))

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

async function loadCollections(keyword = '') {
  const nextQueryId = queryId + 1
  queryId = nextQueryId
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchWorkspaceCollections(keyword)
    if (nextQueryId !== queryId) {
      return
    }
    collections.value = payload
  } catch (err) {
    if (nextQueryId !== queryId) {
      return
    }
    error.value = err.message
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    if (nextQueryId === queryId) {
      loading.value = false
    }
  }
}

function clearSearch() {
  if (!search.value) {
    return
  }
  search.value = ''
}

function retryLoadCollections() {
  loadCollections(search.value.trim())
}

function openCreateCollectionModal() {
  editingCollectionSlug.value = ''
  formModalKey.value += 1
  isFormModalOpen.value = true
}

function openEditCollectionModal(collection) {
  if (collection.is_deleted) {
    return
  }
  editingCollectionSlug.value = collection.slug
  formModalKey.value += 1
  isFormModalOpen.value = true
}

function closeCollectionFormModal() {
  isFormModalOpen.value = false
}

async function handleCollectionSaved() {
  closeCollectionFormModal()
  await loadCollections(search.value.trim())
}

watch(search, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    loadCollections(value.trim())
  }, 250)
})

onMounted(() => {
  loadCollections()
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
})
</script>

<template>
  <section class="operations-panel operations-panel--collections">
    <div class="operations-panel__copy">
      <h1>{{ pageTitle }}</h1>
      <div class="operations-panel__chips" aria-label="Skill 集合状态摘要">
        <span>{{ resultSummary }}</span>
        <span>{{ isAdmin ? '全部归属用户' : '仅我的上传记录' }}</span>
        <span v-if="isAdmin">正常 {{ activeCount }} / 删除 {{ deletedCount }}</span>
      </div>
    </div>

    <label class="search-field search-field--admin operations-panel__search" for="workspace-collection-search">
      <div class="search-field__meta">
        <span class="search-field__label">{{ searchHint }}</span>
        <span class="search-field__status">{{ loading ? '检索中' : `${collections.length} 条结果` }}</span>
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
          id="workspace-collection-search"
          v-model.trim="search"
          class="text-input"
          type="search"
          placeholder="搜索 Skill 集合名称、slug 或用途关键词"
        />
        <button v-if="search" class="search-field__clear" type="button" @click="clearSearch">
          清空
        </button>
      </div>
    </label>

    <div class="operations-panel__actions">
      <button class="button" type="button" @click="openCreateCollectionModal">新增 Skill 集合</button>
    </div>
  </section>

  <ListState
    :error="blockingError"
    :loading="loading && !collections.length"
    :empty="!collections.length"
    loading-text="正在加载 Skill 集合列表..."
    :empty-text="emptyStateText"
    @retry="retryLoadCollections"
  >
    <section v-if="refreshError" class="feedback feedback--error list-state">
      <span>{{ refreshError }}</span>
      <button class="button button--ghost" type="button" @click="retryLoadCollections">重试</button>
    </section>

    <section class="registry-panel">
      <div class="registry-panel__header">
        <h2>Skill 集合资产</h2>
        <p>{{ loading ? '正在刷新列表...' : resultSummary }}</p>
      </div>

      <section class="admin-table-wrap registry-table-wrap" :class="{ 'is-refreshing': loading }">
        <table class="admin-table">
          <thead>
            <tr>
              <th scope="col">Skill 集合</th>
              <th v-if="isAdmin" scope="col">归属用户</th>
              <th scope="col">可见范围</th>
              <th scope="col">版本</th>
              <th scope="col">条目</th>
              <th scope="col">安装命令</th>
              <th v-if="isAdmin" scope="col">状态</th>
              <th scope="col">更新时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="collection in collections" :key="collection.id" :class="{ 'admin-table__row--deleted': collection.is_deleted }">
              <td data-label="Skill 集合">
                <router-link class="admin-table__title" :to="`/workspace/collections/${collection.slug}`">
                  {{ collection.name }}
                </router-link>
                <small class="admin-table__subtext">{{ collection.slug }}</small>
              </td>
              <td v-if="isAdmin" data-label="归属用户">{{ collection.owner_username || '-' }}</td>
              <td data-label="可见范围">{{ getCollectionScopeLabel(collection) }}</td>
              <td data-label="版本">
                <span class="version-chip">{{ collection.current_version }}</span>
              </td>
              <td data-label="条目">{{ collection.item_count }}</td>
              <td data-label="安装命令">
                <code class="admin-table__command">{{ collection.install_command }}</code>
              </td>
              <td v-if="isAdmin" data-label="状态">
                <span class="status-chip" :class="{ 'status-chip--deleted': collection.is_deleted }">
                  {{ collection.is_deleted ? '已删除' : '正常' }}
                </span>
              </td>
              <td data-label="更新时间">{{ formatDate(collection.updated_at) }}</td>
            <td data-label="操作">
              <button
                v-if="!collection.is_deleted"
                class="button button--ghost button--compact"
                type="button"
                @click="openEditCollectionModal(collection)"
              >
                编辑
              </button>
              <router-link class="button button--ghost button--compact" :to="`/workspace/collections/${collection.slug}`">
                打开
              </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </section>
  </ListState>

  <InfoModal
    :open="isFormModalOpen"
    :title="editingCollectionSlug ? '编辑 Skill 集合' : '新增 Skill 集合'"
    :summary="editingCollectionSlug ? '上传新版本或调整集合描述、可见范围。' : '上传集合 ZIP 并填写名称、slug 与可见范围。'"
    width="1040px"
    @close="closeCollectionFormModal"
  >
    <CollectionFormView
      v-if="isFormModalOpen"
      :key="formModalKey"
      embedded
      :collection-slug="editingCollectionSlug"
      @close="closeCollectionFormModal"
      @saved="handleCollectionSaved"
    />
  </InfoModal>
</template>
