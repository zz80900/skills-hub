<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { getWorkspaceRoute, login, setSession } from '../../services/api'

const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const error = ref('')
const form = reactive({
  username: '',
  password: '',
})

async function handleSubmit() {
  submitting.value = true
  error.value = ''
  try {
    const payload = await login(form)
    setSession(payload.access_token, payload.user)
    await router.push(typeof route.query.redirect === 'string' ? route.query.redirect : getWorkspaceRoute())
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--narrow">
      <section class="admin-panel">
        <div class="admin-panel__heading">
          <p class="eyebrow">登录</p>
          <h1>进入 Skill 工作台</h1>
          <p>管理员可查看全部 Skill 和用户列表，普通用户仅可管理自己上传的 Skill。</p>
        </div>

        <form class="form-card" @submit.prevent="handleSubmit">
          <label class="field">
            <span>用户名</span>
            <input v-model="form.username" class="text-input" type="text" autocomplete="username" />
          </label>
          <label class="field">
            <span>密码</span>
            <input
              v-model="form.password"
              class="text-input"
              type="password"
              autocomplete="current-password"
            />
          </label>
          <p v-if="error" class="feedback feedback--error">{{ error }}</p>
          <button class="button" :disabled="submitting" type="submit">
            {{ submitting ? '登录中...' : '登录' }}
          </button>
        </form>
      </section>
    </main>
  </div>
</template>
