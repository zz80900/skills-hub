<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import GroupManagementPanel from '../../components/user-center/GroupManagementPanel.vue'
import SkillManagementPanel from '../../components/user-center/SkillManagementPanel.vue'
import UserManagementPanel from '../../components/user-center/UserManagementPanel.vue'
import { authState, fetchWorkspaceGroups, getUserDisplayName } from '../../services/api'

const route = useRoute()
const router = useRouter()
const loadingGroupAccess = ref(true)
const hasManagedGroups = ref(false)

const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const userCenterLabel = computed(() => {
  if (!authState.user) {
    return '用户中心'
  }
  return getUserDisplayName(authState.user)
})

const tabs = computed(() => {
  const items = [{ key: 'skills', label: 'Skill 管理' }]
  if (isAdmin.value || hasManagedGroups.value) {
    items.push({ key: 'groups', label: '组管理' })
  }
  if (isAdmin.value) {
    items.push({ key: 'users', label: '用户管理' })
  }
  return items
})

const activeTab = computed(() => {
  const requestedTab = typeof route.query.tab === 'string' ? route.query.tab : 'skills'
  return tabs.value.some((item) => item.key === requestedTab) ? requestedTab : tabs.value[0]?.key || 'skills'
})

const centerSummary = computed(() => {
  if (loadingGroupAccess.value) {
    return '正在同步用户中心权限...'
  }
  if (activeTab.value === 'groups') {
    return '统一维护用户组与组员，支持管理员治理与组长成员维护。'
  }
  if (activeTab.value === 'users') {
    return '管理员可维护账号状态、角色和密码。'
  }
  return '统一查看并管理 Skill、用户组与账号能力。'
})

function switchTab(nextTab) {
  if (!tabs.value.some((item) => item.key === nextTab)) {
    return
  }
  router.replace({
    name: 'workspace-dashboard',
    query: nextTab === 'skills' ? {} : { tab: nextTab },
  })
}

async function loadGroupAccess() {
  if (isAdmin.value) {
    hasManagedGroups.value = true
    loadingGroupAccess.value = false
    return
  }

  try {
    const groups = await fetchWorkspaceGroups()
    hasManagedGroups.value = groups.length > 0
  } catch {
    hasManagedGroups.value = false
  } finally {
    loadingGroupAccess.value = false
  }
}

watch(
  tabs,
  (nextTabs) => {
    if (loadingGroupAccess.value && !isAdmin.value) {
      return
    }
    const requestedTab = typeof route.query.tab === 'string' ? route.query.tab : 'skills'
    if (nextTabs.some((item) => item.key === requestedTab)) {
      return
    }
    switchTab(nextTabs[0]?.key || 'skills')
  },
  { immediate: true },
)

onMounted(() => {
  loadGroupAccess()
})
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content">
      <section class="admin-toolbar">
        <div class="admin-toolbar__intro">
          <p class="eyebrow">用户中心</p>
          <h1>{{ userCenterLabel }}</h1>
          <p class="admin-toolbar__summary">{{ centerSummary }}</p>
        </div>
        <div class="admin-toolbar__actions user-center-switches">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="button button--ghost"
            :class="{ 'button--active': activeTab === tab.key }"
            type="button"
            @click="switchTab(tab.key)"
          >
            {{ tab.label }}
          </button>
        </div>
      </section>

      <SkillManagementPanel v-if="activeTab === 'skills'" />
      <GroupManagementPanel v-else-if="activeTab === 'groups'" />
      <UserManagementPanel v-else />
    </main>
  </div>
</template>
