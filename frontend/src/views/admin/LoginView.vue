<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { login, setToken } from '../../services/api'

const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const error = ref('')
const form = reactive({
  username: 'admin',
  password: 'admin',
})

async function handleSubmit() {
  submitting.value = true
  error.value = ''
  try {
    const payload = await login(form)
    setToken(payload.access_token)
    await router.push(route.query.redirect || '/admin')
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
          <p class="eyebrow">管理后台</p>
          <h1>管理员登录</h1>
          <p>默认账号密码为 <code>admin / admin</code>，建议上线前通过环境变量覆盖。</p>
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
            {{ submitting ? '登录中...' : '登录后台' }}
          </button>
        </form>
      </section>
    </main>
  </div>
</template>

