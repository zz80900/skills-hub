<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import InfoModal from '../InfoModal.vue'
import {
  authState,
  createUser,
  fetchUsers,
  getUserDisplayName,
  resetUserPassword,
  updateUser,
} from '../../services/api'

const router = useRouter()
const loading = ref(false)
const loadingMore = ref(false)
const submitting = ref(false)
const resettingId = ref(null)
const listError = ref('')
const actionError = ref('')
const loadMoreError = ref('')
const formError = ref('')
const users = ref([])
const search = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const hasMore = ref(false)
const isUserModalOpen = ref(false)
const editingUserId = ref(null)
const editingUserSource = ref('LOCAL')
const userSentinel = ref(null)
const form = reactive({
  username: '',
  password: '',
  role: 'USER',
  is_active: true,
})

let searchTimer = null
let userObserver = null
let activeQueryId = 0

const isEditMode = computed(() => editingUserId.value !== null)
const isEditingAdUser = computed(() => isEditMode.value && editingUserSource.value === 'AD')
const submitLabel = computed(() => {
  if (submitting.value) {
    return '提交中...'
  }
  return isEditMode.value ? '保存用户' : '创建用户'
})
const modalTitle = computed(() => (isEditMode.value ? '修改账号信息' : '创建新账号'))
const modalSummary = computed(() =>
  isEditMode.value
    ? '可编辑角色和启用状态；本地用户可重置密码，AD 用户账号信息由域控同步。'
    : '管理员只能手工创建本地账号，AD 用户会在首次登录时自动建档。',
)
const emptyStateText = computed(() => (search.value ? '未找到匹配用户。' : '当前还没有用户。'))
const resultsSummary = computed(() => {
  if (!total.value) {
    return search.value ? '未找到匹配用户' : '当前没有用户'
  }
  return search.value ? `匹配 ${total.value} 个用户` : `当前共 ${total.value} 个账号`
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

function formatSource(source) {
  return source === 'AD' ? 'AD 域' : '本地'
}

function resetForm() {
  editingUserId.value = null
  editingUserSource.value = 'LOCAL'
  form.username = ''
  form.password = ''
  form.role = 'USER'
  form.is_active = true
  formError.value = ''
}

function closeUserModal() {
  isUserModalOpen.value = false
  resetForm()
}

function openCreateModal() {
  resetForm()
  isUserModalOpen.value = true
}

function startEdit(user) {
  formError.value = ''
  editingUserId.value = user.id
  editingUserSource.value = user.source
  form.username = user.username
  form.password = ''
  form.role = user.role
  form.is_active = user.is_active
  isUserModalOpen.value = true
}

function mergeUsers(items) {
  const merged = [...users.value]
  const seen = new Set(merged.map((user) => user.id))
  items.forEach((item) => {
    if (!seen.has(item.id)) {
      seen.add(item.id)
      merged.push(item)
    }
  })
  users.value = merged
}

async function loadUsers(options = {}) {
  const nextPage = options.page || 1
  const append = Boolean(options.append)
  const keyword = typeof options.query === 'string' ? options.query : search.value
  const queryId = append ? activeQueryId : activeQueryId + 1

  if (!append) {
    activeQueryId = queryId
    loading.value = true
    loadingMore.value = false
    listError.value = ''
    actionError.value = ''
    loadMoreError.value = ''
  } else {
    loadingMore.value = true
    loadMoreError.value = ''
  }

  try {
    const payload = await fetchUsers(keyword, { page: nextPage, pageSize: pageSize.value })
    if (queryId !== activeQueryId) {
      return
    }

    page.value = payload.page
    pageSize.value = payload.page_size || pageSize.value
    total.value = payload.total || 0
    hasMore.value = Boolean(payload.has_more)

    if (append) {
      mergeUsers(payload.items || [])
    } else {
      users.value = payload.items || []
    }
  } catch (err) {
    if (!authState.token) {
      router.push('/login')
    }
    if (queryId !== activeQueryId) {
      return
    }

    if (append) {
      loadMoreError.value = err.message
    } else {
      listError.value = err.message
      users.value = []
      total.value = 0
      hasMore.value = false
    }
  } finally {
    if (append) {
      loadingMore.value = false
    } else if (queryId === activeQueryId) {
      loading.value = false
    }
  }
}

async function loadMoreUsers() {
  if (loading.value || loadingMore.value || !hasMore.value) {
    return
  }
  await loadUsers({ page: page.value + 1, append: true })
}

async function handleSubmit() {
  submitting.value = true
  formError.value = ''
  try {
    if (isEditMode.value) {
      await updateUser(editingUserId.value, {
        username: form.username,
        role: form.role,
        is_active: form.is_active,
      })
    } else {
      await createUser({
        username: form.username,
        password: form.password,
        role: form.role,
        is_active: form.is_active,
      })
    }
    closeUserModal()
    await loadUsers({ page: 1, query: search.value })
  } catch (err) {
    if (err.message && err.message.includes('挑战')) {
      formError.value = '安全验证失败，请刷新页面后重试'
    } else {
      formError.value = err.message
    }
  } finally {
    submitting.value = false
  }
}

async function handlePasswordReset(user) {
  if (user.source === 'AD') {
    actionError.value = 'AD 用户密码由域控管理，不支持本地重置'
    return
  }

  const nextPassword = window.prompt(`请输入用户「${user.username}」的新密码`)
  if (!nextPassword) {
    return
  }

  resettingId.value = user.id
  actionError.value = ''
  loadMoreError.value = ''
  try {
    await resetUserPassword(user.id, nextPassword)
    await loadUsers({ page: 1, query: search.value })
  } catch (err) {
    if (err.message && err.message.includes('挑战')) {
      actionError.value = '安全验证失败，请刷新页面后重试'
    } else {
      actionError.value = err.message
    }
  } finally {
    resettingId.value = null
  }
}

async function quickToggle(user) {
  actionError.value = ''
  loadMoreError.value = ''
  try {
    await updateUser(user.id, { is_active: !user.is_active })
    await loadUsers({ page: 1, query: search.value })
  } catch (err) {
    actionError.value = err.message
  }
}

function resetUserObserver() {
  if (userObserver) {
    userObserver.disconnect()
    userObserver = null
  }
}

async function syncUserObserver() {
  resetUserObserver()
  await nextTick()
  if (
    typeof IntersectionObserver === 'undefined'
    || typeof window === 'undefined'
    || !userSentinel.value
    || !users.value.length
    || !hasMore.value
    || loading.value
    || loadingMore.value
    || listError.value
    || loadMoreError.value
  ) {
    return
  }

  userObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        loadMoreUsers()
      }
    },
    { rootMargin: '320px 0px' },
  )
  userObserver.observe(userSentinel.value)
}

watch(search, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    loadUsers({ page: 1, query: value })
  }, 250)
})

watch(
  [hasMore, loading, loadingMore, listError, loadMoreError, () => users.value.length],
  () => {
    syncUserObserver()
  },
)

onMounted(() => {
  loadUsers({ page: 1 })
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
  resetUserObserver()
})
</script>

<template>
  <section class="admin-toolbar">
    <div class="admin-toolbar__intro">
      <p class="eyebrow">用户管理</p>
      <h1>账号与权限</h1>
      <p class="admin-toolbar__summary">支持按用户名或姓名搜索，滚动到底部自动加载更多账号。</p>
    </div>
    <div class="admin-toolbar__actions">
      <button class="button" type="button" @click="openCreateModal">新增用户</button>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel__heading">
      <p class="eyebrow">用户列表</p>
      <h2>全部账号</h2>
      <p>管理员可以编辑用户信息、停启账号和重置密码。</p>
    </div>

    <div class="user-management__controls">
      <label class="search-field search-field--admin user-management__search" for="user-search">
        <div class="search-field__meta">
          <span class="search-field__label">搜索用户名或姓名</span>
          <span class="search-field__status">{{ resultsSummary }}</span>
        </div>
        <div class="search-field__control">
          <span class="search-field__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path
                d="M21 21l-4.35-4.35m1.85-5.15a7 7 0 11-14 0 7 7 0 0114 0z"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.8"
              />
            </svg>
          </span>
          <input
            id="user-search"
            v-model.trim="search"
            class="text-input"
            type="search"
            placeholder="例如：admin、alice、张三"
          />
          <button v-if="search" class="search-field__clear" type="button" @click="search = ''">清空</button>
        </div>
      </label>
    </div>

    <section v-if="actionError" class="feedback feedback--error">{{ actionError }}</section>
    <section v-if="listError" class="feedback feedback--error">{{ listError }}</section>
    <section v-else-if="loading && !users.length" class="feedback">正在加载用户列表...</section>
    <section v-else-if="!users.length" class="feedback">{{ emptyStateText }}</section>
    <template v-else>
      <section class="admin-table-wrap">
        <table class="admin-table admin-table--users">
          <thead>
            <tr>
              <th scope="col">用户名</th>
              <th scope="col">姓名</th>
              <th scope="col">来源</th>
              <th scope="col">角色</th>
              <th scope="col">状态</th>
              <th scope="col">创建时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <div class="user-table__title">
                  <strong>{{ user.username }}</strong>
                  <small v-if="authState.user?.id === user.id">当前登录账号</small>
                  <small v-else-if="user.external_principal">{{ user.external_principal }}</small>
                </div>
              </td>
              <td>{{ getUserDisplayName(user) }}</td>
              <td>{{ formatSource(user.source) }}</td>
              <td>{{ user.role === 'ADMIN' ? '管理员' : '普通用户' }}</td>
              <td>
                <span class="status-chip" :class="{ 'status-chip--deleted': !user.is_active }">
                  {{ user.is_active ? '启用中' : '已停用' }}
                </span>
              </td>
              <td>{{ formatDate(user.created_at) }}</td>
              <td>
                <div class="admin-table__actions">
                  <button class="button button--ghost" type="button" @click="startEdit(user)">编辑</button>
                  <button class="button button--ghost" type="button" @click="quickToggle(user)">
                    {{ user.is_active ? '停用' : '启用' }}
                  </button>
                  <button
                    class="button button--ghost"
                    type="button"
                    :disabled="resettingId === user.id || user.source === 'AD'"
                    @click="handlePasswordReset(user)"
                  >
                    {{ resettingId === user.id ? '处理中...' : user.source === 'AD' ? '域控管理' : '重置密码' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <div ref="userSentinel" class="user-management__sentinel" aria-hidden="true"></div>

      <section v-if="loadMoreError" class="feedback feedback--error user-management__load-more">
        <span>{{ loadMoreError }}</span>
        <button class="button button--ghost" type="button" @click="loadMoreUsers">重试加载</button>
      </section>
      <section v-else-if="loadingMore" class="feedback user-management__load-more">正在加载更多用户...</section>
      <p v-else class="user-management__footer">
        {{ hasMore ? '继续向下滚动以加载更多用户' : `已加载全部 ${total} 个用户` }}
      </p>
    </template>
  </section>

  <InfoModal :open="isUserModalOpen" :title="modalTitle" :summary="modalSummary" width="720px" @close="closeUserModal">
    <form class="form-card form-card--modal" @submit.prevent="handleSubmit">
      <label class="field">
        <span>用户名</span>
        <input v-model="form.username" class="text-input" type="text" :disabled="isEditingAdUser" />
      </label>
      <p v-if="isEditingAdUser" class="feedback feedback--inline">AD 用户名由域账号映射，不支持手动修改。</p>
      <label v-if="!isEditMode" class="field">
        <span>初始密码</span>
        <input v-model="form.password" class="text-input" type="password" />
      </label>
      <label class="field">
        <span>角色</span>
        <select v-model="form.role" class="text-input">
          <option value="USER">普通用户</option>
          <option value="ADMIN">管理员</option>
        </select>
      </label>
      <label class="field field--inline">
        <input v-model="form.is_active" type="checkbox" />
        <span>启用账号</span>
      </label>
      <p v-if="formError" class="feedback feedback--error feedback--inline">{{ formError }}</p>
      <div class="form-actions">
        <button class="button" :disabled="submitting" type="submit">{{ submitLabel }}</button>
        <button class="button button--ghost" type="button" @click="closeUserModal">取消</button>
      </div>
    </form>
  </InfoModal>
</template>
