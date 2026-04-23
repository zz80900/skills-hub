<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import InfoModal from '../InfoModal.vue'
import {
  authState,
  addGroupMember,
  createGroup,
  deleteGroup,
  fetchGroupMemberOptions,
  fetchWorkspaceGroups,
  getUserDisplayName,
  removeGroupMember,
  updateGroup,
} from '../../services/api'

const router = useRouter()
const loading = ref(false)
const savingGroup = ref(false)
const deletingGroup = ref(false)
const addingMemberId = ref(null)
const removingMemberId = ref(null)
const loadError = ref('')
const groupError = ref('')
const memberError = ref('')
const addMemberError = ref('')
const groups = ref([])
const memberOptions = ref([])
const selectedGroupId = ref(null)
const addMemberSearch = ref('')
const isAddMemberModalOpen = ref(false)

const form = reactive({
  name: '',
  description: '',
  leader_user_id: '',
})

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const currentUserId = computed(() => authState.user?.id || null)
const selectedGroup = computed(() => groups.value.find((item) => item.id === selectedGroupId.value) || null)
const canManageAnyGroup = computed(() =>
  isAdmin.value || groups.value.some((group) => group.leader_user_id === currentUserId.value),
)
const canManageSelectedGroup = computed(() =>
  Boolean(selectedGroup.value) && (isAdmin.value || selectedGroup.value?.leader_user_id === currentUserId.value),
)
const pageTitle = computed(() => {
  if (isAdmin.value) {
    return '组管理'
  }
  return canManageAnyGroup.value ? '我负责的用户组' : '我加入的用户组'
})
const pageSummary = computed(() => {
  if (loading.value) {
    return '正在同步用户组数据...'
  }
  if (!groups.value.length) {
    return isAdmin.value ? '当前还没有用户组。' : '当前还没有加入任何用户组。'
  }
  return canManageAnyGroup.value ? `当前共 ${groups.value.length} 个可见用户组` : `当前共加入 ${groups.value.length} 个用户组`
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
const currentMembers = computed(() => {
  if (!selectedGroup.value) {
    return []
  }
  return [...selectedGroup.value.members].sort((left, right) => {
    if (left.id === selectedGroup.value.leader_user_id) {
      return -1
    }
    if (right.id === selectedGroup.value.leader_user_id) {
      return 1
    }
    return left.username.localeCompare(right.username, 'zh-CN')
  })
})
const availableMemberOptions = computed(() => {
  if (!selectedGroup.value) {
    return []
  }
  const keyword = addMemberSearch.value.trim().toLowerCase()
  const existingIds = new Set(selectedGroup.value.members.map((member) => member.id))
  return memberOptions.value
    .filter((user) => !existingIds.has(user.id))
    .filter((user) => {
      if (!keyword) {
        return true
      }
      const displayName = (user.display_name || '').toLowerCase()
      return user.username.toLowerCase().includes(keyword) || displayName.includes(keyword)
    })
})

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
  addMemberError.value = ''
  if (!selectedGroup.value) {
    resetGroupForm()
    return
  }
  form.name = selectedGroup.value.name
  form.description = selectedGroup.value.description || ''
  form.leader_user_id = String(selectedGroup.value.leader_user_id)
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

function closeAddMemberModal() {
  isAddMemberModalOpen.value = false
  addMemberSearch.value = ''
  addMemberError.value = ''
}

function openAddMemberModal() {
  if (!selectedGroup.value) {
    return
  }
  addMemberSearch.value = ''
  addMemberError.value = ''
  isAddMemberModalOpen.value = true
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
    await loadGroups()
    if (isAdmin.value || groups.value.some((group) => group.leader_user_id === currentUserId.value)) {
      await loadMemberOptions()
    } else {
      memberOptions.value = []
    }
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

async function handleAddMember(user) {
  if (!selectedGroup.value || addingMemberId.value || !canManageSelectedGroup.value) {
    return
  }

  addingMemberId.value = user.id
  addMemberError.value = ''
  try {
    const response = await addGroupMember(selectedGroup.value.id, user.id)
    replaceGroupLocally(response)
    await loadMemberOptions()
    closeAddMemberModal()
  } catch (err) {
    addMemberError.value = err.message
  } finally {
    addingMemberId.value = null
  }
}

async function handleRemoveMember(member) {
  if (
    !selectedGroup.value
    || removingMemberId.value
    || member.id === selectedGroup.value.leader_user_id
    || !canManageSelectedGroup.value
  ) {
    return
  }

  const confirmed = window.confirm(`确认将成员「${formatUserLabel(member)}」移出组「${selectedGroup.value.name}」吗？`)
  if (!confirmed) {
    return
  }

  removingMemberId.value = member.id
  memberError.value = ''
  try {
    const response = await removeGroupMember(selectedGroup.value.id, member.id)
    replaceGroupLocally(response)
    await loadMemberOptions()
  } catch (err) {
    memberError.value = err.message
  } finally {
    removingMemberId.value = null
  }
}

function startCreateGroup() {
  selectedGroupId.value = null
  resetGroupForm()
  groupError.value = ''
  memberError.value = ''
  addMemberError.value = ''
}

watch(selectedGroupId, () => {
  syncSelectedGroupState()
})

onMounted(() => {
  loadPage()
})
</script>

<template>
  <section class="admin-toolbar">
    <div class="admin-toolbar__intro">
      <p class="eyebrow">用户组</p>
      <h1>{{ pageTitle }}</h1>
      <p class="admin-toolbar__summary">{{ pageSummary }}</p>
    </div>
    <div class="admin-toolbar__actions">
      <button v-if="isAdmin" class="button" type="button" @click="startCreateGroup">新建用户组</button>
    </div>
  </section>

  <section v-if="loadError" class="feedback feedback--error">{{ loadError }}</section>
  <section v-else-if="loading" class="feedback">正在加载用户组...</section>
  <section v-else class="group-layout">
    <section class="admin-panel group-panel">
      <div class="admin-panel__heading">
        <p class="eyebrow">组列表</p>
        <h2>{{ isAdmin ? '全部用户组' : canManageAnyGroup ? '我负责和参与的用户组' : '我参与的用户组' }}</h2>
        <p>{{ isAdmin ? '管理员可维护组定义并指定组长。' : canManageAnyGroup ? '组长可维护自己负责的组，普通组员可查看自己所在的组。' : '你可以查看自己所在的组和组内成员。' }}</p>
      </div>

      <section v-if="!groups.length" class="feedback">
        {{ isAdmin ? '当前还没有用户组，请先创建。' : '当前还没有加入任何用户组。' }}
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
          <p>管理员负责组名、组说明和组长任命；成员维护在下方单独处理。</p>
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
          <p class="eyebrow">{{ canManageSelectedGroup ? '成员维护' : '组成员' }}</p>
          <h2>{{ selectedGroup.name }}</h2>
          <p>
            当前组长：{{ selectedGroupLead }}，当前共有 {{ currentMembers.length }} 位组员。
            <template v-if="!canManageSelectedGroup">你当前只有查看权限。</template>
          </p>
        </div>

        <div v-if="canManageSelectedGroup" class="group-member-actions">
          <button class="button" type="button" @click="openAddMemberModal">新增组员</button>
        </div>

        <section v-if="memberError" class="feedback feedback--error">{{ memberError }}</section>
        <section v-if="!currentMembers.length" class="feedback">当前还没有组员。</section>
        <div v-else class="group-member-list">
          <article v-for="member in currentMembers" :key="member.id" class="group-member-row">
            <div>
              <strong>{{ formatUserLabel(member) }}</strong>
              <p>
                {{ member.id === selectedGroup.leader_user_id ? '组长' : member.role === 'ADMIN' ? '管理员' : '普通用户' }}
                · {{ member.is_active ? '启用中' : '已停用' }}
              </p>
            </div>
            <div class="group-member-row__actions">
              <span v-if="member.id === selectedGroup.leader_user_id" class="status-chip">组长</span>
              <button
                v-else-if="canManageSelectedGroup"
                class="button button--ghost"
                type="button"
                :disabled="removingMemberId === member.id"
                @click="handleRemoveMember(member)"
              >
                {{ removingMemberId === member.id ? '移除中...' : '删除' }}
              </button>
            </div>
          </article>
        </div>
      </section>
    </section>
  </section>

  <InfoModal
    :open="isAddMemberModalOpen"
    title="新增组员"
    summary="搜索系统用户并单个添加到当前组，已在组内的用户不会重复显示。"
    width="720px"
    @close="closeAddMemberModal"
  >
    <label class="search-field search-field--admin group-member-search" for="group-member-add-search">
      <div class="search-field__meta">
        <span class="search-field__label">搜索用户名或姓名</span>
        <span class="search-field__status">{{ availableMemberOptions.length }} 个可选用户</span>
      </div>
      <div class="search-field__control">
        <input
          id="group-member-add-search"
          v-model.trim="addMemberSearch"
          class="text-input"
          type="search"
          placeholder="例如：admin、alice、张三"
        />
        <button v-if="addMemberSearch" class="search-field__clear" type="button" @click="addMemberSearch = ''">
          清空
        </button>
      </div>
    </label>

    <section v-if="addMemberError" class="feedback feedback--error">{{ addMemberError }}</section>
    <section v-if="!availableMemberOptions.length" class="feedback">当前没有可添加的用户。</section>
    <div v-else class="group-member-modal-list">
      <article v-for="user in availableMemberOptions" :key="user.id" class="group-member-row">
        <div>
          <strong>{{ formatUserLabel(user) }}</strong>
          <p>{{ user.role === 'ADMIN' ? '管理员' : '普通用户' }} · {{ user.is_active ? '启用中' : '已停用' }}</p>
        </div>
        <div class="group-member-row__actions">
          <button
            class="button"
            type="button"
            :disabled="addingMemberId === user.id"
            @click="handleAddMember(user)"
          >
            {{ addingMemberId === user.id ? '添加中...' : '添加' }}
          </button>
        </div>
      </article>
    </div>
  </InfoModal>
</template>
