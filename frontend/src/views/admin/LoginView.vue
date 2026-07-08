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
    if (err.message && err.message.includes('挑战')) {
      error.value = '安全验证失败，请刷新页面后重试'
    } else {
      error.value = err.message || '登录失败'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--login">
      <section class="login-shell">
        <div class="login-copy">
          <h1>NEXGO Skills</h1>
          <div class="login-signal">
            <span>Local Skills</span>
            <span>Group Scope</span>
            <span>Version Flow</span>
          </div>
        </div>

        <form class="form-card login-card" @submit.prevent="handleSubmit">
          <div class="login-card__heading">
            <h2>登录</h2>
          </div>
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
