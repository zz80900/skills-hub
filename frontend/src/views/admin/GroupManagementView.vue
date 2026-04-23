<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import {
  authState,
  createGroup,
  deleteGroup,
  fetchGroupMemberOptions,
  fetchWorkspaceGroups,
  getUserDisplayName,
  updateGroup,
  updateGroupMembers,
} from '../../services/api'

const router = useRouter()
const loading = ref(false)
const savingGroup = ref(false)
const savingMembers = ref(false)
const deletingGroup = ref(false)
const loadError = ref('')
const groupError = ref('')
const memberError = ref('')
const groups = ref([])
const memberOptions = ref([])
const selectedGroupId = ref(null)
const memberSearch = ref('')
const selectedMemberIds = ref([])

const form = reactive({
  name: '',
  description: '',
  leader_user_id: '',
})

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const selectedGroup = computed(() => groups.value.find((item) => item.id === selectedGroupId.value) || null)
const pageTitle = computed(() => (isAdmin.value ? '用户组管理' : '我负责的用户组'))
const pageSummary = computed(() => {
  if (loading.value) {
    return '正在同步用户组数据...'
  }
  if (!groups.value.length) {
    return isAdmin.value ? '当前还没有用户组。' : '当前没有你负责的用户组。'
  }
  return `当前共 ${groups.value.length} 个可管理用户组`
})
const groupSubmitLabel = computed(() => {
  if (savingGroup.value) {
    return '提交中...'
  }
  return selectedGroup.value ? '保存组信息' : '创建用户组'
})
const selectedGroupLead = computed(() => {
  if (!selectedGroup.value) {
    return ''
  }
  return selectedGroup.value.leader_display_name
    ? `${selectedGroup.value.leader_display_name} (${selectedGroup.value.leader_username})`
    : selectedGroup.value.leader_username
})
const filteredMemberOptions = computed(() => {
  const keyword = memberSearch.value.trim().toLowerCase()
  if (!keyword) {
    return memberOptions.value
  }
  return memberOptions.value.filter((user) => {
    const displayName = (user.display_name || '').toLowerCase()
    return user.username.toLowerCase().includes(keyword) || displayName.includes(keyword)
  })
})
const selectedMemberCount = computed(() => selectedMemberIds.value.length)

function formatUserLabel(user) {
  const displayName = getUserDisplayName(user)
  return displayName === user.username ? user.username : `${displayName} (${user.username})`
}

function resetGroupForm() {
  form.name = ''
  form.description = ''
  form.leader_user_id = ''
}

function syncSelectedGroupState() {
  groupError.value = ''
  memberError.value = ''
  if (!selectedGroup.value) {
    resetGroupForm()
    selectedMemberIds.value = []
    return
  }
  form.name = selectedGroup.value.name
  form.description = selectedGroup.value.description || ''
  form.leader_user_id = String(selectedGroup.value.leader_user_id)
  selectedMemberIds.value = selectedGroup.value.members.map((member) => member.id)
}

function replaceGroupLocally(nextGroup) {
  const nextGroups = [...groups.value]
  const index = nextGroups.findIndex((item) => item.id === nextGroup.id)
  if (index >= 0) {
    nextGroups[index] = nextGroup
  } else {
    nextGroups.unshift(nextGroup)
  }
  groups.value = nextGroups
  selectedGroupId.value = nextGroup.id
  syncSelectedGroupState()
}

async function loadGroups() {
  groups.value = await fetchWorkspaceGroups()
  if (!groups.value.length) {
    selectedGroupId.value = null
    syncSelectedGroupState()
    return
  }
  if (!selectedGroupId.value || !groups.value.some((group) => group.id === selectedGroupId.value)) {
    selectedGroupId.value = groups.value[0].id
  }
  syncSelectedGroupState()
}

async function loadMemberOptions() {
  try {
    memberOptions.value = await fetchGroupMemberOptions()
  } catch (err) {
    if (err.message === '当前用户没有可管理的组') {
      memberOptions.value = []
      return
    }
    throw err
  }
}

async function loadPage() {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([loadGroups(), loadMemberOptions()])
  } catch (err) {
    loadError.value = err.message
    if (!authState.token) {
      router.push('/login')
    }
  } finally {
    loading.value = false
  }
}

async function handleGroupSubmit() {
  if (!isAdmin.value) {
    return
  }

  savingGroup.value = true
  groupError.value = ''
  try {
    const normalizedName = form.name.trim()
    if (!normalizedName) {
      throw new Error('请输入组名')
    }
    if (!form.leader_user_id) {
      throw new Error('请选择组长')
    }

    const payload = {
      name: normalizedName,
      description: form.description.trim() || null,
      leader_user_id: Number(form.leader_user_id),
    }
    const response = selectedGroup.value
      ? await updateGroup(selectedGroup.value.id, payload)
      : await createGroup(payload)
    replaceGroupLocally(response)
    await loadMemberOptions()
  } catch (err) {
    groupError.value = err.message
  } finally {
    savingGroup.value = false
  }
}

async function handleDeleteGroup() {
  if (!isAdmin.value || !selectedGroup.value || deletingGroup.value) {
    return
  }

  const confirmed = window.confirm(`确认删除用户组「${selectedGroup.value.name}」吗？该操作不可恢复。`)
  if (!confirmed) {
    return
  }

  deletingGroup.value = true
  groupError.value = ''
  memberError.value = ''
  try {
    await deleteGroup(selectedGroup.value.id)
    await loadGroups()
    await loadMemberOptions()
  } catch (err) {
    groupError.value = err.message
  } finally {
    deletingGroup.value = false
  }
}

async function handleMemberSubmit() {
  if (!selectedGroup.value) {
    return
  }

  savingMembers.value = true
  memberError.value = ''
  try {
    if (!selectedMemberIds.value.length) {
      throw new Error('请至少保留组长为组成员')
    }
    const response = await updateGroupMembers(selectedGroup.value.id, selectedMemberIds.value)
    replaceGroupLocally(response)
  } catch (err) {
    memberError.value = err.message
  } finally {
    savingMembers.value = false
  }
}

function startCreateGroup() {
  selectedGroupId.value = null
  resetGroupForm()
  selectedMemberIds.value = []
  groupError.value = ''
  memberError.value = ''
}

watch(selectedGroupId, () => {
  syncSelectedGroupState()
})

onMounted(() => {
  loadPage()
})
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content">
      <section class="admin-toolbar">
        <div class="admin-toolbar__intro">
          <p class="eyebrow">用户组</p>
          <h1>{{ pageTitle }}</h1>
          <p class="admin-toolbar__summary">{{ pageSummary }}</p>
        </div>
        <div class="admin-toolbar__actions">
          <router-link class="button button--ghost" to="/workspace">返回工作台</router-link>
          <button v-if="isAdmin" class="button" type="button" @click="startCreateGroup">新建用户组</button>
        </div>
      </section>

      <section v-if="loadError" class="feedback feedback--error">{{ loadError }}</section>
      <section v-else-if="loading" class="feedback">正在加载用户组...</section>
      <section v-else class="group-layout">
        <section class="admin-panel group-panel">
          <div class="admin-panel__heading">
            <p class="eyebrow">组列表</p>
            <h2>{{ isAdmin ? '全部用户组' : '我负责的用户组' }}</h2>
            <p>{{ isAdmin ? '管理员可维护组定义并指定组长。' : '组长可查看自己负责的小组并维护成员。' }}</p>
          </div>

          <section v-if="!groups.length" class="feedback">
            {{ isAdmin ? '当前还没有用户组，请先创建。' : '当前没有你负责的用户组。' }}
          </section>
          <div v-else class="group-list">
            <button
              v-for="group in groups"
              :key="group.id"
              class="group-list__item"
              :class="{ 'is-active': selectedGroupId === group.id }"
              type="button"
              @click="selectedGroupId = group.id"
            >
              <div class="group-list__title-row">
                <strong>{{ group.name }}</strong>
                <span class="status-chip">{{ group.member_count }} 人</span>
              </div>
              <p>{{ group.description || '未填写组说明' }}</p>
              <small>组长：{{ group.leader_display_name || group.leader_username }}</small>
            </button>
          </div>
        </section>

        <section class="group-layout__main">
          <section v-if="isAdmin" class="admin-panel group-panel">
            <div class="admin-panel__heading">
              <p class="eyebrow">组定义</p>
              <h2>{{ selectedGroup ? '编辑用户组' : '创建用户组' }}</h2>
              <p>管理员负责组名、组说明和组长任命；成员维护在下方单独保存。</p>
            </div>

            <form class="form-card" @submit.prevent="handleGroupSubmit">
              <label class="field">
                <span>组名</span>
                <input v-model="form.name" class="text-input" type="text" placeholder="例如：PLM 组" />
              </label>

              <label class="field">
                <span>组说明</span>
                <textarea
                  v-model="form.description"
                  class="text-area"
                  rows="4"
                  placeholder="描述该组的业务范围或共享规范"
                />
              </label>

              <label class="field">
                <span>组长</span>
                <select v-model="form.leader_user_id" class="text-input">
                  <option value="">请选择组长</option>
                  <option v-for="user in memberOptions" :key="user.id" :value="String(user.id)">
                    {{ formatUserLabel(user) }}
                  </option>
                </select>
              </label>

              <p v-if="groupError" class="feedback feedback--error feedback--inline">{{ groupError }}</p>
              <div class="form-actions">
                <button class="button" :disabled="savingGroup" type="submit">{{ groupSubmitLabel }}</button>
                <button
                  v-if="selectedGroup"
                  class="button button--ghost"
                  type="button"
                  @click="startCreateGroup"
                >
                  切换为新建
                </button>
                <button
                  v-if="selectedGroup"
                  class="button button--danger"
                  :disabled="deletingGroup"
                  type="button"
                  @click="handleDeleteGroup"
                >
                  {{ deletingGroup ? '删除中...' : '删除组' }}
                </button>
              </div>
            </form>
          </section>

          <section v-if="selectedGroup" class="admin-panel group-panel">
            <div class="admin-panel__heading">
              <p class="eyebrow">成员维护</p>
              <h2>{{ selectedGroup.name }}</h2>
              <p>当前组长：{{ selectedGroupLead }}，共选择 {{ selectedMemberCount }} 位成员。</p>
            </div>

            <label class="search-field search-field--admin group-member-search" for="group-member-search">
              <div class="search-field__meta">
                <span class="search-field__label">搜索用户名或姓名</span>
                <span class="search-field__status">{{ filteredMemberOptions.length }} 个候选用户</span>
              </div>
              <div class="search-field__control">
                <input
                  id="group-member-search"
                  v-model.trim="memberSearch"
                  class="text-input"
                  type="search"
                  placeholder="例如：admin、alice、张三"
                />
                <button v-if="memberSearch" class="search-field__clear" type="button" @click="memberSearch = ''">
                  清空
                </button>
              </div>
            </label>

            <div class="group-member-grid">
              <label v-for="user in filteredMemberOptions" :key="user.id" class="group-member-option">
                <input v-model="selectedMemberIds" type="checkbox" :value="user.id" />
                <div>
                  <strong>{{ formatUserLabel(user) }}</strong>
                  <small>{{ user.role === 'ADMIN' ? '管理员' : '普通用户' }} · {{ user.is_active ? '启用中' : '已停用' }}</small>
                </div>
              </label>
            </div>

            <p v-if="memberError" class="feedback feedback--error feedback--inline">{{ memberError }}</p>
            <div class="form-actions">
              <button class="button" :disabled="savingMembers" type="button" @click="handleMemberSubmit">
                {{ savingMembers ? '保存中...' : '保存成员' }}
              </button>
            </div>

            <div class="group-member-summary">
              <p class="eyebrow">当前成员</p>
              <div class="group-member-tags">
                <span v-for="member in selectedGroup.members" :key="member.id" class="status-chip">
                  {{ formatUserLabel(member) }}
                </span>
              </div>
            </div>
          </section>
        </section>
      </section>
    </main>
  </div>
</template>
