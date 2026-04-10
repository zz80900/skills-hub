<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CommandSnippet from './CommandSnippet.vue'
import InfoModal from './InfoModal.vue'
import {
  authState,
  clearSession,
  fetchPublicConfig,
  getUserDisplayName,
  getWorkspaceRoute,
  isAdmin,
  isAuthenticated,
  logout,
} from '../services/api'

const route = useRoute()
const router = useRouter()
const infoTabs = [
  { key: 'guide', label: '使用教程' },
  { key: 'cli', label: '安装 CLI' },
]
const activeInfoTab = ref('')
const cliInstallCommand = ref('')
const publicConfigLoading = ref(false)
const publicConfigError = ref('')

const loggedIn = computed(() => isAuthenticated())
const isInfoModalOpen = computed(() => Boolean(activeInfoTab.value))
const workspaceLabel = computed(() => (isAdmin() ? '工作台' : '我的 Skill'))
const infoModalTitle = computed(() => (activeInfoTab.value === 'cli' ? '安装 CLI' : '使用教程'))
const infoModalSummary = computed(() =>
  activeInfoTab.value === 'cli'
    ? '先安装 nexgo-skills CLI，再通过首页复制具体 Skill 安装命令。'
    : ' ',
)
const userBadge = computed(() => {
  if (!authState.user) {
    return ''
  }
  const displayName = getUserDisplayName(authState.user)
  const label = displayName === authState.user.username ? displayName : `${displayName} (${authState.user.username})`
  return `${label} · ${authState.user.role === 'ADMIN' ? '管理员' : '普通用户'}`
})
const loginTarget = computed(() => {
  if (route.name === 'login') {
    return { name: 'login' }
  }
  return { name: 'login', query: { redirect: route.fullPath } }
})

async function loadPublicConfig() {
  if (publicConfigLoading.value || cliInstallCommand.value) {
    return
  }

  publicConfigLoading.value = true
  publicConfigError.value = ''
  try {
    const payload = await fetchPublicConfig()
    cliInstallCommand.value = payload.cli_install_command || ''
  } catch (err) {
    publicConfigError.value = err.message || 'CLI 安装命令暂时不可用，请稍后重试。'
  } finally {
    publicConfigLoading.value = false
  }
}

function handleInfoTabClick(tabKey) {
  activeInfoTab.value = activeInfoTab.value === tabKey ? '' : tabKey
  if (activeInfoTab.value === 'cli') {
    loadPublicConfig()
  }
}

function closeInfoModal() {
  activeInfoTab.value = ''
}

async function handleLogout() {
  try {
    await logout()
  } finally {
    clearSession()
    router.push({ name: 'login' })
  }
}

onMounted(() => {
  loadPublicConfig()
})
</script>

<template>
  <header class="site-header">
    <div class="site-header__inner">
      <router-link class="site-header__brand" to="/">NEXGO Skills</router-link>
      <nav class="site-header__nav">
        <router-link
          class="site-header__link"
          to="/"
          active-class="site-header__link--route-active"
          exact-active-class="is-active"
        >
          Skills
        </router-link>
        <button
          v-for="tab in infoTabs"
          :key="tab.key"
          class="site-header__link site-header__link--button"
          :class="{ 'is-active': activeInfoTab === tab.key }"
          type="button"
          :aria-pressed="activeInfoTab === tab.key"
          @click="handleInfoTabClick(tab.key)"
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
  <InfoModal
    :open="isInfoModalOpen"
    :title="infoModalTitle"
    :summary="infoModalSummary"
    width="720px"
    @close="closeInfoModal"
  >
    <ol v-if="activeInfoTab === 'guide'" class="info-modal__list">
      <li>本 CLI 依赖 Node.js 18 及以上版本，请先<a href="https://nodejs.org/en/download/" target="_blank">下载</a>并安装。</li>
      <li>点击“安装 CLI”，复制 nexgo-skills CLI 安装命令到终端执行。</li>
      <li>选择您需要的 Skill，点击卡片查看详情；随后在终端执行相应的 Skill 安装命令即可（支持多种主流 AI IDE）。</li>
      <li>登录工作台后，您还可以上传并分享自己开发的 Skill。</li>
    </ol>
    <CommandSnippet
      v-else-if="activeInfoTab === 'cli' && cliInstallCommand"
      label="CLI 安装命令"
      :command="cliInstallCommand"
      compact
    />
    <section v-else-if="activeInfoTab === 'cli' && publicConfigError" class="feedback feedback--error feedback--inline">
      {{ publicConfigError }}
    </section>
    <section v-else-if="activeInfoTab === 'cli'" class="feedback feedback--inline">
      正在加载 CLI 安装命令...
    </section>
  </InfoModal>
</template>
