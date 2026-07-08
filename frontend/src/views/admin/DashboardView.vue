<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import GroupManagementPanel from '../../components/user-center/GroupManagementPanel.vue'
import SkillManagementPanel from '../../components/user-center/SkillManagementPanel.vue'
import UserManagementPanel from '../../components/user-center/UserManagementPanel.vue'
import { authState, fetchWorkspaceGroups, getUserDisplayName, getUserOrganizationLevels } from '../../services/api'

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
const activeTabItem = computed(() => tabs.value.find((item) => item.key === activeTab.value) || tabs.value[0])
const roleLabel = computed(() => (isAdmin.value ? '管理员' : '成员'))
const centerStatus = computed(() => (loadingGroupAccess.value ? '权限同步中' : roleLabel.value))
const organizationLevels = computed(() => getUserOrganizationLevels(authState.user))

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
    <main class="page-content page-content--workspace">
      <section class="workspace-shell">
        <aside class="workspace-rail">
          <div class="workspace-identity">
            <h1>{{ userCenterLabel }}</h1>
            <span>{{ roleLabel }}</span>
          </div>

          <nav class="workspace-nav" aria-label="用户中心模块">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              class="workspace-tab"
              :class="{ 'is-active': activeTab === tab.key }"
              type="button"
              @click="switchTab(tab.key)"
            >
              <span>{{ tab.label }}</span>
            </button>
          </nav>

          <div v-if="organizationLevels.length" class="workspace-organization">
            <span>当前组织</span>
            <strong>{{ organizationLevels.join(' / ') }}</strong>
          </div>
        </aside>

        <div class="workspace-main">
          <header class="workspace-main__header">
            <h2>{{ activeTabItem?.label || '工作台' }}</h2>
            <span class="workspace-main__status">{{ centerStatus }}</span>
          </header>

          <SkillManagementPanel v-if="activeTab === 'skills'" />
          <GroupManagementPanel v-else-if="activeTab === 'groups'" />
          <UserManagementPanel v-else />
        </div>
      </section>
    </main>
  </div>
</template>
