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
  isAuthenticated,
  logout,
} from '../services/api'

const route = useRoute()
const router = useRouter()
const isGuideModalOpen = ref(false)
const cliInstallCommand = ref('')
const publicConfigLoading = ref(false)
const publicConfigError = ref('')

const loggedIn = computed(() => isAuthenticated())
const userCenterLabel = computed(() => {
  if (!authState.user) {
    return '用户中心'
  }
  return getUserDisplayName(authState.user)
})
const userCenterTooltip = computed(() => {
  if (!authState.user) {
    return '进入用户中心'
  }
  return `${userCenterLabel.value} · ${authState.user.role === 'ADMIN' ? '管理员' : '普通用户'}`
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

function openGuideModal() {
  isGuideModalOpen.value = true
  loadPublicConfig()
}

function closeGuideModal() {
  isGuideModalOpen.value = false
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
      <router-link class="site-header__brand" to="/">
        <span class="site-header__brand-mark" aria-hidden="true">S</span>
        <span class="site-header__brand-copy">
          <strong>NEXGO Skills</strong>
        </span>
      </router-link>
      <nav class="site-header__nav">
        <router-link
          class="site-header__link"
          to="/"
          active-class="site-header__link--route-active"
          exact-active-class="is-active"
        >
          首页
        </router-link>
        <button
          class="site-header__link site-header__link--button"
          :class="{ 'is-active': isGuideModalOpen }"
          type="button"
          :aria-pressed="isGuideModalOpen"
          @click="openGuideModal"
        >
          使用教程
        </button>
        <template v-if="loggedIn">
          <router-link class="site-header__link" :to="getWorkspaceRoute()" :title="userCenterTooltip">
            {{ userCenterLabel }}
          </router-link>
          <button class="site-header__link site-header__link--button" type="button" @click="handleLogout">
            退出
          </button>
        </template>
        <router-link v-else class="site-header__link" :to="loginTarget">登录</router-link>
      </nav>
    </div>
  </header>
  <InfoModal
    :open="isGuideModalOpen"
    title="使用教程"
    summary="在这里完成 CLI 安装、Skill 浏览和登录后管理的完整入门流程。"
    width="760px"
    @close="closeGuideModal"
  >
    <section class="guide-modal__section">
      <h3>1. 安装准备</h3>
      <ol class="info-modal__list">
        <li>本 CLI 依赖 Node.js 18 及以上版本，请先<a href="https://nodejs.org/en/download/" target="_blank"><b>下载</b></a>并安装。</li>
        <li>执行下面的 CLI 安装命令，完成本地命令行工具安装。</li>
      </ol>
    </section>

    <CommandSnippet
      v-if="cliInstallCommand"
      label="CLI 安装命令"
      :command="cliInstallCommand"
      compact
    />
    <section v-else-if="publicConfigError" class="feedback feedback--error feedback--inline">
      {{ publicConfigError }}
    </section>
    <section v-else class="feedback feedback--inline">
      正在加载 CLI 安装命令...
    </section>

    <section class="guide-modal__section">
      <h3>2. 浏览并安装 Skill</h3>
      <ol class="info-modal__list">
        <li>在首页浏览需要的 Skill，点击卡片查看详情。</li>
        <li>复制对应 Skill 的安装命令，并在终端执行安装。</li>
      </ol>
    </section>

    <section class="guide-modal__section">
      <h3>3. 登录后进入用户中心</h3>
      <ol class="info-modal__list">
        <li>登录后点击右上角你的名字，进入用户中心。</li>
        <li>在用户中心内统一切换 Skill 管理、组管理和用户管理（管理员）。</li>
        <li>你也可以在用户中心上传、维护和分享自己开发的 Skill。</li>
      </ol>
    </section>
  </InfoModal>
</template>
