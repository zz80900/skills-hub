<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { createSkill, fetchAdminSkill, updateSkill } from '../../services/api'

const route = useRoute()
const router = useRouter()
const isEditMode = computed(() => Boolean(route.params.name))
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const selectedFileName = ref('')
const form = reactive({
  name: '',
  description_markdown: '',
  zip_file: null,
})

function onFileChange(event) {
  const [file] = event.target.files || []
  form.zip_file = file || null
  selectedFileName.value = file?.name || ''
}

async function loadSkill() {
  if (!isEditMode.value) {
    return
  }
  loading.value = true
  error.value = ''
  try {
    const skill = await fetchAdminSkill(route.params.name)
    form.name = skill.name
    form.description_markdown = skill.description_markdown
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  submitting.value = true
  error.value = ''
  try {
    const payload = new FormData()
    payload.append('description_markdown', form.description_markdown)

    if (isEditMode.value) {
      if (form.zip_file) {
        payload.append('zip_file', form.zip_file)
      }
      await updateSkill(form.name, payload)
    } else {
      payload.append('name', form.name)
      if (!form.zip_file) {
        throw new Error('请上传 ZIP 压缩包')
      }
      payload.append('zip_file', form.zip_file)
      await createSkill(payload)
    }

    router.push('/admin')
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadSkill()
})
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--narrow">
      <section class="admin-panel">
        <div class="admin-panel__heading">
          <p class="eyebrow">管理后台</p>
          <h1>{{ isEditMode ? '编辑 / 升级 Skill' : '新增 Skill' }}</h1>
          <p>上传时只支持 ZIP，并且压缩包内必须包含非空 <code>SKILL.md</code>。</p>
        </div>

        <section v-if="loading" class="feedback">正在加载 Skill...</section>

        <form v-else class="form-card" @submit.prevent="handleSubmit">
          <label class="field">
            <span>Skill 名称</span>
            <input
              v-model="form.name"
              class="text-input"
              type="text"
              :disabled="isEditMode"
              placeholder="例如：plm-assistant"
            />
          </label>

          <label class="field">
            <span>Skill 描述（Markdown）</span>
            <textarea
              v-model="form.description_markdown"
              class="text-area"
              rows="12"
              placeholder="请输入 Skill 描述，支持 Markdown"
            />
          </label>

          <label class="field">
            <span>{{ isEditMode ? '升级 ZIP 包（可选）' : 'ZIP 包' }}</span>
            <input class="file-input" type="file" accept=".zip" @change="onFileChange" />
            <small v-if="selectedFileName">{{ selectedFileName }}</small>
          </label>

          <p v-if="error" class="feedback feedback--error">{{ error }}</p>

          <div class="form-actions">
            <button class="button" :disabled="submitting" type="submit">
              {{ submitting ? '提交中...' : isEditMode ? '保存并升级' : '创建 Skill' }}
            </button>
            <router-link class="button button--ghost" to="/admin">返回列表</router-link>
          </div>
        </form>
      </section>
    </main>
  </div>
</template>

