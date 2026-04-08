<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
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
const submitting = ref(false)
const resettingId = ref(null)
const error = ref('')
const users = ref([])
const editingUserId = ref(null)
const editingUserSource = ref('LOCAL')
const form = reactive({
  username: '',
  password: '',
  role: 'USER',
  is_active: true,
})

const isEditMode = computed(() => editingUserId.value !== null)
const isEditingAdUser = computed(() => isEditMode.value && editingUserSource.value === 'AD')
const submitLabel = computed(() => {
  if (submitting.value) {
    return '提交中...'
  }
  return isEditMode.value ? '保存用户' : '创建用户'
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

function resetForm() {
  editingUserId.value = null
  editingUserSource.value = 'LOCAL'
  form.username = ''
  form.password = ''
  form.role = 'USER'
  form.is_active = true
}

async function loadUsers() {
  loading.value = true
  error.value = ''
  try {
    users.value = await fetchUsers()
  } catch (err) {
    error.value = err.message
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    loading.value = false
  }
}

function startEdit(user) {
  editingUserId.value = user.id
  editingUserSource.value = user.source
  form.username = user.username
  form.password = ''
  form.role = user.role
  form.is_active = user.is_active
}

async function handleSubmit() {
  submitting.value = true
  error.value = ''
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
    resetForm()
    await loadUsers()
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}

async function handlePasswordReset(user) {
  if (user.source === 'AD') {
    error.value = 'AD 用户密码由域控管理，不支持本地重置'
    return
  }
  const nextPassword = window.prompt(`请输入用户「${user.username}」的新密码`)
  if (!nextPassword) {
    return
  }

  resettingId.value = user.id
  error.value = ''
  try {
    await resetUserPassword(user.id, nextPassword)
    await loadUsers()
  } catch (err) {
    error.value = err.message
  } finally {
    resettingId.value = null
  }
}

async function quickToggle(user) {
  error.value = ''
  try {
    await updateUser(user.id, { is_active: !user.is_active })
    await loadUsers()
  } catch (err) {
    error.value = err.message
  }
}

onMounted(() => {
  loadUsers()
})

function formatSource(source) {
  return source === 'AD' ? 'AD 域' : '本地'
}
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content">
      <section class="admin-toolbar">
        <div class="admin-toolbar__intro">
          <p class="eyebrow">用户管理</p>
          <h1>账号与权限</h1>
          <p class="admin-toolbar__summary">角色固定为管理员和普通用户，不提供角色 CRUD。</p>
        </div>
        <div class="admin-toolbar__actions">
          <router-link class="button button--ghost" to="/workspace">返回工作台</router-link>
        </div>
      </section>

      <section class="user-layout">
        <section class="admin-panel">
          <div class="admin-panel__heading">
            <p class="eyebrow">{{ isEditMode ? '编辑用户' : '新增用户' }}</p>
            <h2>{{ isEditMode ? '修改账号信息' : '创建新账号' }}</h2>
            <p>
              {{
                isEditMode
                  ? '可编辑角色和启用状态；本地用户可重置密码，AD 用户账号信息由域控同步。'
                  : '管理员只能手工创建本地账号，AD 用户会在首次登录时自动建档。'
              }}
            </p>
          </div>

          <form class="form-card" @submit.prevent="handleSubmit">
            <label class="field">
              <span>用户名</span>
              <input v-model="form.username" class="text-input" type="text" :disabled="isEditingAdUser" />
            </label>
            <p v-if="isEditingAdUser" class="feedback">AD 用户名由域账号映射，不支持手动修改。</p>
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
            <p v-if="error" class="feedback feedback--error">{{ error }}</p>
            <div class="form-actions">
              <button class="button" :disabled="submitting" type="submit">{{ submitLabel }}</button>
              <button class="button button--ghost" type="button" @click="resetForm">清空</button>
            </div>
          </form>
        </section>

        <section class="admin-panel">
          <div class="admin-panel__heading">
            <p class="eyebrow">用户列表</p>
            <h2>全部账号</h2>
            <p>管理员可以编辑用户信息、停启账号和重置密码。</p>
          </div>
          <section v-if="loading" class="feedback">正在加载用户列表...</section>
          <section v-else-if="!users.length" class="feedback">当前还没有用户。</section>
          <section v-else class="admin-table-wrap admin-table-wrap--embedded">
            <table class="admin-table">
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
        </section>
      </section>
    </main>
  </div>
</template>
