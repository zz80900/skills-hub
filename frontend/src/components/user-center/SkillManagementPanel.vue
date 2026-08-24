<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import InfoModal from '../InfoModal.vue'
import ListState from '../ListState.vue'
import SkillFormView from '../../views/admin/SkillFormView.vue'
import { authState, fetchWorkspaceSkills, getSkillScopeLabel } from '../../services/api'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const search = ref('')
const skills = ref([])
const isFormModalOpen = ref(false)
const editingSkillName = ref('')
const formModalKey = ref(0)
let searchTimer = null
let skillQueryId = 0

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const pageTitle = computed(() => (isAdmin.value ? '全部 Skill' : '我上传的 Skill'))
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
const activeSkillCount = computed(() => skills.value.filter((skill) => !skill.is_deleted).length)
const deletedSkillCount = computed(() => skills.value.filter((skill) => skill.is_deleted).length)
const ownershipSummary = computed(() =>
  isAdmin.value ? '全部归属用户' : '仅我的上传记录',
)
const emptyStateText = computed(() => {
  if (search.value) {
    return `没有找到与“${search.value}”匹配的 Skill。`
  }
  return isAdmin.value ? '当前还没有 Skill 记录。' : '你还没有上传 Skill。'
})
const blockingError = computed(() => (!skills.value.length ? error.value : ''))
const refreshError = computed(() => (skills.value.length ? error.value : ''))

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
  const queryId = skillQueryId + 1
  skillQueryId = queryId
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchWorkspaceSkills(keyword)
    if (queryId !== skillQueryId) {
      return
    }
    skills.value = payload
  } catch (err) {
    if (queryId !== skillQueryId) {
      return
    }
    error.value = err.message
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    if (queryId === skillQueryId) {
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

function retryLoadSkills() {
  loadSkills(search.value.trim())
}

function openCreateSkillModal() {
  editingSkillName.value = ''
  formModalKey.value += 1
  isFormModalOpen.value = true
}

function openEditSkillModal(skill) {
  if (skill.is_deleted) {
    return
  }
  editingSkillName.value = skill.name
  formModalKey.value += 1
  isFormModalOpen.value = true
}

function closeSkillFormModal() {
  isFormModalOpen.value = false
}

async function handleSkillSaved() {
  closeSkillFormModal()
  await loadSkills(search.value.trim())
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
</script>

<template>
  <section class="operations-panel operations-panel--skills">
    <div class="operations-panel__copy">
      <h1>{{ pageTitle }}</h1>
      <div class="operations-panel__chips" aria-label="Skill 状态摘要">
        <span>{{ resultSummary }}</span>
        <span>{{ ownershipSummary }}</span>
        <span v-if="isAdmin">正常 {{ activeSkillCount }} / 删除 {{ deletedSkillCount }}</span>
      </div>
    </div>

    <label class="search-field search-field--admin operations-panel__search" for="workspace-skill-search">
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

    <div class="operations-panel__actions">
      <button class="button" type="button" @click="openCreateSkillModal">新增 Skill</button>
    </div>
  </section>

  <ListState
    :error="blockingError"
    :loading="loading && !skills.length"
    :empty="!skills.length"
    loading-text="正在加载 Skill 列表..."
    :empty-text="emptyStateText"
    @retry="retryLoadSkills"
  >
    <section v-if="refreshError" class="feedback feedback--error list-state">
      <span>{{ refreshError }}</span>
      <button class="button button--ghost" type="button" @click="retryLoadSkills">重试</button>
    </section>

    <section class="registry-panel">
      <div class="registry-panel__header">
        <h2>Skill 资产</h2>
        <p>{{ loading ? '正在刷新列表...' : resultSummary }}</p>
      </div>

      <section class="admin-table-wrap registry-table-wrap" :class="{ 'is-refreshing': loading }">
      <table class="admin-table">
        <thead>
          <tr>
            <th scope="col">标题</th>
            <th v-if="isAdmin" scope="col">归属用户</th>
            <th scope="col">可见范围</th>
            <th scope="col">当前版本</th>
            <th scope="col">上传者</th>
            <th v-if="isAdmin" scope="col">状态</th>
            <th scope="col">更新时间</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="skill in skills" :key="skill.id" :class="{ 'admin-table__row--deleted': skill.is_deleted }">
            <td data-label="标题">
              <router-link class="admin-table__title" :to="`/workspace/skills/${skill.name}`">
                {{ skill.name }}
              </router-link>
            </td>
            <td v-if="isAdmin" data-label="归属用户">{{ skill.owner_username || '-' }}</td>
            <td data-label="可见范围">{{ getSkillScopeLabel(skill) }}</td>
            <td data-label="当前版本">
              <span class="version-chip">{{ skill.current_version }}</span>
            </td>
            <td data-label="上传者">{{ skill.contributor || '-' }}</td>
            <td v-if="isAdmin" data-label="状态">
              <span class="status-chip" :class="{ 'status-chip--deleted': skill.is_deleted }">
                {{ skill.is_deleted ? '已删除' : '正常' }}
              </span>
            </td>
            <td data-label="更新时间">{{ formatDate(skill.updated_at) }}</td>
            <td data-label="操作">
              <button
                v-if="!skill.is_deleted"
                class="button button--ghost button--compact"
                type="button"
                @click="openEditSkillModal(skill)"
              >
                编辑
              </button>
              <router-link class="button button--ghost button--compact" :to="`/workspace/skills/${skill.name}`">
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
    :title="editingSkillName ? '编辑 Skill' : '新增 Skill'"
    :summary="editingSkillName ? '上传新版本或调整描述、可见范围。' : '上传 ZIP 包并填写 Skill 的基本信息。'"
    width="1040px"
    @close="closeSkillFormModal"
  >
    <SkillFormView
      v-if="isFormModalOpen"
      :key="formModalKey"
      embedded
      :skill-name="editingSkillName"
      @close="closeSkillFormModal"
      @saved="handleSkillSaved"
    />
  </InfoModal>
</template>
