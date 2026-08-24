<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import ConfirmDialog from '../ConfirmDialog.vue'
import InfoModal from '../InfoModal.vue'
import ListState from '../ListState.vue'
import {
  acceptGroupInvitation,
  authState,
  cancelGroupInvitation,
  createWorkspaceGroup,
  deleteWorkspaceGroup,
  fetchGroupInvitations,
  fetchGroupMemberOptions,
  fetchWorkspaceGroups,
  getUserDisplayName,
  inviteGroupMember,
  rejectGroupInvitation,
  removeGroupMember,
  transferGroupLeader,
  updateWorkspaceGroup,
} from '../../services/api'
import { notifySuccess } from '../../services/feedback'

const router = useRouter()
const loading = ref(false)
const savingGroup = ref(false)
const deletingGroup = ref(false)
const addingMemberId = ref(null)
const removingMemberId = ref(null)
const processingInvitationId = ref(null)
const cancellingInvitationUserId = ref(null)
const transferringMemberId = ref(null)
const loadError = ref('')
const invitationError = ref('')
const groupError = ref('')
const memberError = ref('')
const addMemberError = ref('')
const pendingActionError = ref('')
const groups = ref([])
const invitations = ref([])
const memberOptions = ref([])
const selectedGroupId = ref(null)
const addMemberSearch = ref('')
const isGroupModalOpen = ref(false)
const isAddMemberModalOpen = ref(false)
const pendingAction = ref(null)

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
const createdGroupCount = computed(() =>
  groups.value.filter((group) => group.created_by_user_id === currentUserId.value).length,
)
const pageSummary = computed(() => {
  if (loading.value && !groups.value.length && !invitations.value.length) {
    return '正在同步用户组与邀请...'
  }
  if (!groups.value.length && !invitations.value.length) {
    return '尚未加入用户组，可立即创建自己的组。'
  }
  return `${groups.value.length} 个有效组 · ${invitations.value.length} 条待处理邀请`
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
  return [...(selectedGroup.value.members || [])].sort((left, right) => {
    if (left.id === selectedGroup.value.leader_user_id) {
      return -1
    }
    if (right.id === selectedGroup.value.leader_user_id) {
      return 1
    }
    return left.username.localeCompare(right.username, 'zh-CN')
  })
})
const selectedPendingInvitations = computed(() => selectedGroup.value?.pending_invitations || [])
const availableMemberOptions = computed(() => {
  if (!selectedGroup.value) {
    return []
  }
  const keyword = addMemberSearch.value.trim().toLowerCase()
  const unavailableIds = new Set([
    ...(selectedGroup.value.members || []).map((member) => member.id),
    ...selectedPendingInvitations.value.map((invitation) => invitation.user_id),
  ])
  return memberOptions.value
    .filter((user) => user.is_active && !unavailableIds.has(user.id))
    .filter((user) => {
      if (!keyword) {
        return true
      }
      const displayName = (user.display_name || '').toLowerCase()
      return user.username.toLowerCase().includes(keyword) || displayName.includes(keyword)
    })
})
const pendingActionBusy = computed(() => {
  const action = pendingAction.value
  if (!action) {
    return false
  }
  if (action.type === 'delete-group') {
    return deletingGroup.value
  }
  if (action.type === 'remove-member') {
    return removingMemberId.value === action.member?.id
  }
  if (action.type === 'transfer-leader') {
    return transferringMemberId.value === action.member?.id
  }
  if (action.type === 'cancel-invitation') {
    return cancellingInvitationUserId.value === action.invitation?.user_id
  }
  return false
})
const pendingActionTitle = computed(() => {
  const action = pendingAction.value
  if (action?.type === 'delete-group') {
    return '删除用户组'
  }
  if (action?.type === 'remove-member') {
    return '移除已确认成员'
  }
  if (action?.type === 'transfer-leader') {
    return '转移组长'
  }
  if (action?.type === 'cancel-invitation') {
    return '取消待确认邀请'
  }
  return '确认操作'
})
const pendingActionSummary = computed(() => {
  const action = pendingAction.value
  if (action?.type === 'delete-group') {
    return `删除「${action.group.name}」及其成员和邀请记录`
  }
  if (action?.type === 'remove-member') {
    return `将「${formatUserLabel(action.member)}」移出「${action.group.name}」`
  }
  if (action?.type === 'transfer-leader') {
    return `将「${action.group.name}」的组长转移给「${formatUserLabel(action.member)}」`
  }
  if (action?.type === 'cancel-invitation') {
    return `取消发给「${formatInvitationUser(action.invitation)}」的邀请`
  }
  return ''
})
const pendingActionConfirmLabel = computed(() => {
  if (pendingAction.value?.type === 'delete-group') {
    return '确认删除'
  }
  if (pendingAction.value?.type === 'remove-member') {
    return '确认移除'
  }
  if (pendingAction.value?.type === 'transfer-leader') {
    return '确认转移'
  }
  if (pendingAction.value?.type === 'cancel-invitation') {
    return '确认取消'
  }
  return '确认'
})

function formatUserLabel(user) {
  const displayName = getUserDisplayName(user)
  return displayName === user.username ? user.username : `${displayName} (${user.username})`
}

function formatInvitationUser(invitation) {
  if (!invitation) {
    return '未知用户'
  }
  return invitation.display_name
    ? `${invitation.display_name} (${invitation.username})`
    : invitation.username
}

function formatInvitationTime(value) {
  if (!value) {
    return '邀请时间未知'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '邀请时间未知'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function groupAccessLabel(group) {
  if (group.leader_user_id === currentUserId.value) {
    return '我负责'
  }
  return isAdmin.value ? '管理员视图' : '已加入'
}

function resetGroupForm() {
  form.name = ''
  form.description = ''
  form.leader_user_id = isAdmin.value ? '' : String(currentUserId.value || '')
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

function clearPendingAction() {
  pendingAction.value = null
  pendingActionError.value = ''
}

function closePendingAction() {
  if (pendingActionBusy.value) {
    return
  }
  clearPendingAction()
}

function openAddMemberModal() {
  if (!selectedGroup.value || !canManageSelectedGroup.value) {
    return
  }
  addMemberSearch.value = ''
  addMemberError.value = ''
  isAddMemberModalOpen.value = true
}

function openEditGroupModal() {
  if (!canManageSelectedGroup.value) {
    return
  }
  syncSelectedGroupState()
  isGroupModalOpen.value = true
}

function closeGroupModal() {
  if (savingGroup.value) {
    return
  }
  isGroupModalOpen.value = false
  syncSelectedGroupState()
}

async function loadGroups() {
  const nextGroups = await fetchWorkspaceGroups()
  groups.value = nextGroups
  if (!nextGroups.length) {
    selectedGroupId.value = null
    syncSelectedGroupState()
    return
  }
  if (!selectedGroupId.value || !nextGroups.some((group) => group.id === selectedGroupId.value)) {
    selectedGroupId.value = nextGroups[0].id
  }
  syncSelectedGroupState()
}

async function loadInvitations() {
  invitations.value = await fetchGroupInvitations()
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
  invitationError.value = ''
  const [groupResult, invitationResult] = await Promise.allSettled([
    loadGroups(),
    loadInvitations(),
  ])

  if (groupResult.status === 'rejected') {
    loadError.value = groupResult.reason?.message || '用户组加载失败，请重试'
  }
  if (invitationResult.status === 'rejected') {
    invitationError.value = invitationResult.reason?.message || '待处理邀请加载失败，请重试'
  }

  if (groupResult.status === 'fulfilled' && canManageAnyGroup.value) {
    try {
      await loadMemberOptions()
    } catch (err) {
      memberError.value = err.message
    }
  } else if (groupResult.status === 'fulfilled') {
    memberOptions.value = []
  }

  if (!authState.token) {
    router.push('/login')
  }
  loading.value = false
}

async function retryInvitations() {
  invitationError.value = ''
  try {
    await loadInvitations()
  } catch (err) {
    invitationError.value = err.message
  }
}

function retryLoadPage() {
  loadPage()
}

async function handleGroupSubmit() {
  if (selectedGroup.value && !canManageSelectedGroup.value) {
    return
  }

  savingGroup.value = true
  groupError.value = ''
  try {
    const isEditing = Boolean(selectedGroup.value)
    const normalizedName = form.name.trim()
    if (!normalizedName) {
      throw new Error('请输入组名')
    }
    const payload = {
      name: normalizedName,
      description: form.description.trim() || null,
    }
    if (!isEditing && isAdmin.value) {
      if (!form.leader_user_id) {
        throw new Error('请选择组长')
      }
      payload.leader_user_id = Number(form.leader_user_id)
    }

    const response = isEditing
      ? await updateWorkspaceGroup(selectedGroup.value.id, payload)
      : await createWorkspaceGroup(payload)
    replaceGroupLocally(response)
    notifySuccess(isEditing ? '用户组信息已更新' : '用户组已创建')
    await loadMemberOptions()
    isGroupModalOpen.value = false
  } catch (err) {
    groupError.value = err.message
  } finally {
    savingGroup.value = false
  }
}

function handleDeleteGroup() {
  if (!selectedGroup.value || deletingGroup.value || !canManageSelectedGroup.value) {
    return
  }
  pendingAction.value = { type: 'delete-group', group: selectedGroup.value }
  pendingActionError.value = ''
}

async function handleAddMember(user) {
  if (!selectedGroup.value || addingMemberId.value || !canManageSelectedGroup.value) {
    return
  }

  addingMemberId.value = user.id
  addMemberError.value = ''
  try {
    const response = await inviteGroupMember(selectedGroup.value.id, user.id)
    replaceGroupLocally(response)
    notifySuccess(`已向 ${formatUserLabel(user)} 发出邀请`)
    closeAddMemberModal()
  } catch (err) {
    addMemberError.value = err.message
  } finally {
    addingMemberId.value = null
  }
}

function handleRemoveMember(member) {
  if (
    !selectedGroup.value
    || removingMemberId.value
    || member.id === selectedGroup.value.leader_user_id
    || !canManageSelectedGroup.value
  ) {
    return
  }
  pendingAction.value = { type: 'remove-member', group: selectedGroup.value, member }
  pendingActionError.value = ''
}

function handleTransferLeader(member) {
  if (!selectedGroup.value || transferringMemberId.value || !canManageSelectedGroup.value) {
    return
  }
  pendingAction.value = { type: 'transfer-leader', group: selectedGroup.value, member }
  pendingActionError.value = ''
}

function handleCancelInvitation(invitation) {
  if (!selectedGroup.value || cancellingInvitationUserId.value || !canManageSelectedGroup.value) {
    return
  }
  pendingAction.value = { type: 'cancel-invitation', group: selectedGroup.value, invitation }
  pendingActionError.value = ''
}

async function handleInvitationDecision(invitation, decision) {
  if (processingInvitationId.value) {
    return
  }
  processingInvitationId.value = invitation.membership_id
  invitationError.value = ''
  try {
    if (decision === 'accept') {
      await acceptGroupInvitation(invitation.membership_id)
      notifySuccess(`已加入「${invitation.group_name}」`)
    } else {
      await rejectGroupInvitation(invitation.membership_id)
      notifySuccess(`已拒绝「${invitation.group_name}」的邀请`)
    }
    await loadPage()
  } catch (err) {
    invitationError.value = err.message
  } finally {
    processingInvitationId.value = null
  }
}

async function confirmPendingAction() {
  const action = pendingAction.value
  if (!action) {
    return
  }

  pendingActionError.value = ''
  if (action.type === 'delete-group') {
    deletingGroup.value = true
    try {
      await deleteWorkspaceGroup(action.group.id)
      notifySuccess('用户组已删除')
      clearPendingAction()
      isGroupModalOpen.value = false
      await loadPage()
    } catch (err) {
      pendingActionError.value = err.message
    } finally {
      deletingGroup.value = false
    }
    return
  }

  if (action.type === 'remove-member') {
    removingMemberId.value = action.member.id
    try {
      const response = await removeGroupMember(action.group.id, action.member.id)
      replaceGroupLocally(response)
      notifySuccess('成员已移出用户组')
      clearPendingAction()
    } catch (err) {
      pendingActionError.value = err.message
    } finally {
      removingMemberId.value = null
    }
    return
  }

  if (action.type === 'transfer-leader') {
    transferringMemberId.value = action.member.id
    try {
      await transferGroupLeader(action.group.id, action.member.id)
      notifySuccess('组长已转移')
      clearPendingAction()
      await loadPage()
    } catch (err) {
      pendingActionError.value = err.message
    } finally {
      transferringMemberId.value = null
    }
    return
  }

  if (action.type === 'cancel-invitation') {
    cancellingInvitationUserId.value = action.invitation.user_id
    try {
      const response = await cancelGroupInvitation(action.group.id, action.invitation.user_id)
      replaceGroupLocally(response)
      notifySuccess('待确认邀请已取消')
      clearPendingAction()
    } catch (err) {
      pendingActionError.value = err.message
    } finally {
      cancellingInvitationUserId.value = null
    }
  }
}

function startCreateGroup() {
  selectedGroupId.value = null
  resetGroupForm()
  groupError.value = ''
  memberError.value = ''
  addMemberError.value = ''
  isGroupModalOpen.value = true
}

watch(selectedGroupId, () => {
  syncSelectedGroupState()
})

onMounted(() => {
  loadPage()
})
</script>

<template>
  <section class="operations-panel operations-panel--groups">
    <div class="operations-panel__copy">
      <h1>组管理</h1>
      <div class="operations-panel__chips" aria-label="组管理状态">
        <span>{{ pageSummary }}</span>
        <span>{{ canManageAnyGroup ? '组长可维护定义、成员和邀请' : '已确认成员为只读状态' }}</span>
        <span>可见自建组 {{ createdGroupCount }} / 20</span>
      </div>
    </div>
    <div class="operations-panel__actions">
      <button class="button" type="button" @click="startCreateGroup">创建用户组</button>
    </div>
  </section>

  <section class="group-invitation-panel" aria-labelledby="group-invitation-title">
    <div class="group-invitation-panel__header">
      <div>
        <h2 id="group-invitation-title">待处理邀请</h2>
        <p>接受后才会成为已确认成员，并获得该组范围资源权限。</p>
      </div>
      <span class="status-chip status-chip--pending">{{ invitations.length }} 条待确认</span>
    </div>

    <section v-if="invitationError" class="feedback feedback--error group-invitation-panel__feedback" aria-live="polite">
      <span>{{ invitationError }}</span>
      <button class="button button--ghost" type="button" @click="retryInvitations">重试</button>
    </section>
    <section v-else-if="loading && !invitations.length" class="feedback group-invitation-panel__feedback">
      正在同步待处理邀请...
    </section>
    <section v-else-if="!invitations.length" class="group-invitation-empty">
      当前没有待处理邀请。别人发出的邀请会显示在这里，不会提前计入你的有效组。
    </section>
    <div v-else class="group-invitation-list">
      <article v-for="invitation in invitations" :key="invitation.membership_id" class="group-invitation-row">
        <div class="group-invitation-row__copy">
          <strong>{{ invitation.group_name }}</strong>
          <p>
            组长：{{ invitation.leader_username }}
            · 邀请人：{{ invitation.invited_by_username || '系统用户' }}
            · {{ formatInvitationTime(invitation.invited_at) }}
          </p>
        </div>
        <div class="group-invitation-row__actions">
          <span class="status-chip status-chip--pending">待确认</span>
          <button
            class="button"
            type="button"
            :disabled="processingInvitationId === invitation.membership_id"
            @click="handleInvitationDecision(invitation, 'accept')"
          >
            {{ processingInvitationId === invitation.membership_id ? '处理中...' : '接受' }}
          </button>
          <button
            class="button button--ghost"
            type="button"
            :disabled="processingInvitationId === invitation.membership_id"
            @click="handleInvitationDecision(invitation, 'reject')"
          >
            拒绝
          </button>
        </div>
      </article>
    </div>
  </section>

  <ListState
    :error="''"
    :loading="loading && !groups.length && !invitations.length"
    :empty="false"
    loading-text="正在加载用户组..."
  >
    <section v-if="loadError" class="feedback feedback--error list-state" aria-live="polite">
      <span>{{ loadError }}</span>
      <button class="button button--ghost" type="button" @click="retryLoadPage">重试</button>
    </section>

    <section class="group-workbench" :class="{ 'is-refreshing': loading }">
      <section class="group-directory">
        <div class="group-directory__header">
          <div>
            <h2>{{ isAdmin ? '全部用户组' : '我负责和已加入的组' }}</h2>
            <p>这里只统计组长和已确认成员关系，待确认邀请不会出现在列表中。</p>
          </div>
          <div class="group-directory__actions">
            <span class="group-directory__count">{{ groups.length }} 个有效组</span>
          </div>
        </div>

        <div class="group-list group-list--directory">
          <div class="group-list__header" aria-hidden="true">
            <span>用户组</span>
            <span>组说明</span>
            <span>组长</span>
            <span>成员</span>
            <span>状态</span>
          </div>

          <section v-if="!groups.length" class="group-directory-empty">
            <strong>还没有有效用户组</strong>
            <p>创建一个组后，你会立即成为组长和首个已确认成员。</p>
            <button class="button button--ghost" type="button" @click="startCreateGroup">创建第一个组</button>
          </section>

          <button
            v-for="group in groups"
            :key="group.id"
            class="group-list__item"
            :class="{ 'is-active': selectedGroupId === group.id }"
            type="button"
            :aria-pressed="selectedGroupId === group.id"
            @click="selectedGroupId = group.id"
          >
            <span class="group-list__cell group-list__cell--name">
              <strong>{{ group.name }}</strong>
              <small>ID：{{ group.id }}</small>
            </span>
            <span class="group-list__cell group-list__cell--description">
              <span>{{ group.description || '未填写组说明' }}</span>
            </span>
            <span class="group-list__cell group-list__cell--leader">
              <span>{{ group.leader_display_name || group.leader_username }}</span>
              <small>{{ group.leader_username }}</small>
            </span>
            <span class="group-list__cell group-list__cell--count">
              <strong>{{ group.member_count }} / 100</strong>
              <small>已确认成员</small>
            </span>
            <span class="group-list__cell group-list__cell--status">
              <span class="status-chip">{{ groupAccessLabel(group) }}</span>
              <small v-if="group.pending_invitation_count">{{ group.pending_invitation_count }} 条待确认</small>
              <small v-else>{{ selectedGroupId === group.id ? '当前选中' : '点击查看' }}</small>
            </span>
          </button>
        </div>
      </section>

      <section class="group-workbench__main">
        <section v-if="selectedGroup" class="admin-panel group-panel group-member-panel">
          <div class="section-heading section-heading--inline">
            <div>
              <h2>{{ selectedGroup.name }}</h2>
              <div class="section-heading__chips">
                <span class="status-chip">组长：{{ selectedGroupLead }}</span>
                <span class="status-chip">{{ currentMembers.length }} / 100 位已确认成员</span>
                <span v-if="!canManageSelectedGroup" class="status-chip status-chip--readonly">只读成员</span>
              </div>
            </div>
            <div class="section-heading__actions">
              <button v-if="canManageSelectedGroup" class="button button--ghost" type="button" @click="openEditGroupModal">
                编辑组信息
              </button>
              <button v-if="canManageSelectedGroup" class="button" type="button" @click="openAddMemberModal">
                发出邀请
              </button>
            </div>
          </div>

          <section v-if="memberError" class="feedback feedback--error" aria-live="polite">{{ memberError }}</section>
          <div class="group-section-heading">
            <div>
              <h3>已确认成员</h3>
              <p>这些用户当前属于该组，并参与组范围权限校验。</p>
            </div>
            <span class="status-chip">{{ currentMembers.length }} 人</span>
          </div>
          <div class="group-member-list">
            <article v-for="member in currentMembers" :key="member.id" class="group-member-row">
              <div class="group-member-row__copy">
                <strong>{{ formatUserLabel(member) }}</strong>
                <p>
                  {{ member.id === selectedGroup.leader_user_id ? '当前组长' : member.role === 'ADMIN' ? '管理员成员' : '普通成员' }}
                  · {{ member.is_active ? '账号启用' : '账号已停用' }}
                  · 已确认
                </p>
              </div>
              <div class="group-member-row__actions">
                <span v-if="member.id === selectedGroup.leader_user_id" class="status-chip">组长</span>
                <template v-else-if="canManageSelectedGroup">
                  <button class="button button--ghost" type="button" @click="handleTransferLeader(member)">
                    转为组长
                  </button>
                  <button class="button button--danger" type="button" @click="handleRemoveMember(member)">
                    移除
                  </button>
                </template>
                <span v-else class="status-chip status-chip--readonly">已确认</span>
              </div>
            </article>
          </div>

          <section v-if="canManageSelectedGroup" class="group-pending-section">
            <div class="group-section-heading">
              <div>
                <h3>待确认邀请</h3>
                <p>接受前不会计入 100 人容量，也不会获得该组权限。</p>
              </div>
              <span class="status-chip status-chip--pending">{{ selectedPendingInvitations.length }} 条</span>
            </div>
            <section v-if="!selectedPendingInvitations.length" class="group-pending-empty">
              当前没有待确认邀请。
            </section>
            <div v-else class="group-member-list">
              <article
                v-for="invitation in selectedPendingInvitations"
                :key="invitation.membership_id"
                class="group-member-row group-member-row--pending"
              >
                <div class="group-member-row__copy">
                  <strong>{{ formatInvitationUser(invitation) }}</strong>
                  <p>
                    {{ formatInvitationTime(invitation.invited_at) }}
                    · 邀请人：{{ invitation.invited_by_username || '系统用户' }}
                  </p>
                </div>
                <div class="group-member-row__actions">
                  <span class="status-chip status-chip--pending">待确认</span>
                  <button class="button button--ghost" type="button" @click="handleCancelInvitation(invitation)">
                    取消邀请
                  </button>
                </div>
              </article>
            </div>
          </section>
        </section>
        <section v-else class="admin-panel group-panel group-member-panel group-member-panel--empty">
          <div class="section-heading">
            <h2>选择或创建用户组</h2>
            <p>选择上方列表中的有效组查看成员；也可以创建新组并成为组长。</p>
          </div>
          <button class="button" type="button" @click="startCreateGroup">创建用户组</button>
        </section>
      </section>
    </section>
  </ListState>

  <InfoModal
    :open="isGroupModalOpen"
    :title="selectedGroup ? '编辑用户组' : '创建用户组'"
    :summary="selectedGroup ? '名称和说明会立即用于组管理展示；组长转移请在成员列表中操作。' : '创建后由组长维护成员邀请，每个用户最多创建 20 个组。'"
    width="680px"
    @close="closeGroupModal"
  >
    <form class="form-card form-card--flat modal-form group-editor-form" @submit.prevent="handleGroupSubmit">
      <label class="field">
        <span>组名</span>
        <input
          v-model="form.name"
          class="text-input"
          type="text"
          maxlength="128"
          required
          autocomplete="off"
          placeholder="例如：PLM 组"
        />
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

      <label v-if="isAdmin && !selectedGroup" class="field">
        <span>组长</span>
        <select v-model="form.leader_user_id" class="text-input" required>
          <option value="">请选择组长</option>
          <option v-for="user in memberOptions" :key="user.id" :value="String(user.id)">
            {{ formatUserLabel(user) }}
          </option>
        </select>
      </label>
      <p v-else-if="!selectedGroup" class="group-form-note">
        你会成为该组的组长和首个已确认成员。
      </p>
      <p v-else class="group-form-note">
        当前组长：{{ selectedGroupLead }}。如需变更，请从已确认成员中执行“转为组长”。
      </p>

      <p v-if="groupError" class="feedback feedback--error feedback--inline" aria-live="polite">{{ groupError }}</p>
      <div class="form-actions">
        <button class="button" :disabled="savingGroup" type="submit">{{ groupSubmitLabel }}</button>
        <button class="button button--ghost" type="button" @click="closeGroupModal">取消</button>
        <button
          v-if="selectedGroup && canManageSelectedGroup"
          class="button button--danger"
          :disabled="deletingGroup"
          type="button"
          @click="handleDeleteGroup"
        >
          删除组
        </button>
      </div>
    </form>
  </InfoModal>

  <InfoModal
    :open="isAddMemberModalOpen"
    title="邀请用户加入组"
    summary="邀请发送后处于待确认状态，对方接受前不会成为组员，也不会获得组范围权限。"
    width="720px"
    @close="closeAddMemberModal"
  >
    <label class="search-field search-field--admin group-member-search" for="group-member-add-search">
      <div class="search-field__meta">
        <span class="search-field__label">搜索用户名或姓名</span>
        <span class="search-field__status">{{ availableMemberOptions.length }} 个可邀请用户</span>
      </div>
      <div class="search-field__control">
        <input
          id="group-member-add-search"
          v-model.trim="addMemberSearch"
          class="text-input"
          type="search"
          autocomplete="off"
          placeholder="例如：admin、alice、张三"
        />
        <button v-if="addMemberSearch" class="search-field__clear" type="button" @click="addMemberSearch = ''">
          清空
        </button>
      </div>
    </label>

    <section v-if="addMemberError" class="feedback feedback--error" aria-live="polite">{{ addMemberError }}</section>
    <section v-if="!availableMemberOptions.length" class="feedback">
      当前没有可邀请用户。已确认成员和待确认用户不会重复显示。
    </section>
    <div v-else class="group-member-modal-list">
      <article v-for="user in availableMemberOptions" :key="user.id" class="group-member-row">
        <div class="group-member-row__copy">
          <strong>{{ formatUserLabel(user) }}</strong>
          <p>{{ user.role === 'ADMIN' ? '管理员' : '普通用户' }} · 账号启用</p>
        </div>
        <div class="group-member-row__actions">
          <button
            class="button"
            type="button"
            :disabled="addingMemberId === user.id"
            @click="handleAddMember(user)"
          >
            {{ addingMemberId === user.id ? '发送中...' : '发送邀请' }}
          </button>
        </div>
      </article>
    </div>
  </InfoModal>

  <ConfirmDialog
    :open="Boolean(pendingAction)"
    :title="pendingActionTitle"
    :summary="pendingActionSummary"
    :confirm-label="pendingActionConfirmLabel"
    :busy="pendingActionBusy"
    @close="closePendingAction"
    @confirm="confirmPendingAction"
  >
    <p v-if="pendingAction?.type === 'delete-group'">
      仅未被 Skill 或 Skill 集合引用的组可以删除；删除成功后无法恢复成员和邀请记录。
    </p>
    <p v-else-if="pendingAction?.type === 'transfer-leader'">
      转移后，新组长获得管理权限；你会保留为普通已确认成员。
    </p>
    <p v-else-if="pendingAction?.type === 'remove-member'">
      移除成功后，该用户会立即失去由此组获得的资源权限。
    </p>
    <p v-else-if="pendingAction?.type === 'cancel-invitation'">
      取消后，对方将无法再接受本次邀请；需要加入时可重新发出邀请。
    </p>
    <p v-if="pendingActionError" class="feedback feedback--error feedback--inline" aria-live="polite">
      {{ pendingActionError }}
    </p>
  </ConfirmDialog>
</template>
