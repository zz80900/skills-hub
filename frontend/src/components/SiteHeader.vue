<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { authState, clearSession, getWorkspaceRoute, isAdmin, isAuthenticated, logout } from '../services/api'

defineProps({
  tabs: {
    type: Array,
    default: () => [],
  },
  activeTab: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['tab-select'])
const route = useRoute()
const router = useRouter()

const loggedIn = computed(() => isAuthenticated())
const workspaceLabel = computed(() => (isAdmin() ? '工作台' : '我的 Skill'))
const userBadge = computed(() => {
  if (!authState.user) {
    return ''
  }
  return `${authState.user.username} · ${authState.user.role === 'ADMIN' ? '管理员' : '普通用户'}`
})
const loginTarget = computed(() => {
  if (route.name === 'login') {
    return { name: 'login' }
  }
  return { name: 'login', query: { redirect: route.fullPath } }
})

function handleTabClick(tabKey) {
  emit('tab-select', tabKey)
}

async function handleLogout() {
  try {
    await logout()
  } finally {
    clearSession()
    router.push({ name: 'login' })
  }
}
</script>

<template>
  <header class="site-header">
    <div class="site-header__inner">
      <router-link class="site-header__brand" to="/">SSC Skills Library</router-link>
      <nav class="site-header__nav">
        <router-link class="site-header__link" to="/">Skills</router-link>
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="site-header__link site-header__link--button"
          :class="{ 'is-active': activeTab === tab.key }"
          type="button"
          @click="handleTabClick(tab.key)"
        >
          {{ tab.label }}
        </button>
        <template v-if="loggedIn">
          <router-link class="site-header__link" :to="getWorkspaceRoute()">{{ workspaceLabel }}</router-link>
          <router-link v-if="isAdmin()" class="site-header__link" to="/workspace/users">用户管理</router-link>
          <span class="site-header__badge">{{ userBadge }}</span>
          <button class="site-header__link site-header__link--button" type="button" @click="handleLogout">
            退出
          </button>
        </template>
        <router-link v-else class="site-header__link" :to="loginTarget">登录</router-link>
      </nav>
    </div>
  </header>
</template>
