<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import InfoModal from './InfoModal.vue'
import {
  authState,
  clearSession,
  getUserDisplayName,
  getWorkspaceRoute,
  isAuthenticated,
  logout,
} from '../services/api'

const route = useRoute()
const router = useRouter()
const isGuideModalOpen = ref(false)

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

function openGuideModal() {
  isGuideModalOpen.value = true
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
    summary="在这里完成 Skill 浏览和登录后管理的完整入门流程。"
    width="760px"
    @close="closeGuideModal"
  >
    <section class="guide-modal__section">
      <h3>1. 准备 Node.js</h3>
      <ol class="info-modal__list">
        <li>Skill 安装命令通过 npx 执行，请先安装 Node.js 18 及以上版本。</li>
        <li>如果本机已经可以执行 node 和 npx，可以直接进入下一步。</li>
      </ol>
    </section>

    <section class="guide-modal__section">
      <h3>2. 浏览 Skill</h3>
      <ol class="info-modal__list">
        <li>在首页浏览本地库与 skills.sh，点击卡片查看详情。</li>
        <li>在详情页复制 Skill 安装命令，直接执行即可。</li>
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
