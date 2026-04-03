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
const currentVersion = ref('')
const form = reactive({
  name: '',
  contributor: '',
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
    form.contributor = skill.contributor || ''
    form.description_markdown = skill.description_markdown
    currentVersion.value = skill.current_version
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
    payload.append('contributor', form.contributor.trim())
    payload.append('contributor_submitted', 'true')
    payload.append('description_markdown', form.description_markdown)

    if (isEditMode.value) {
      if (form.zip_file) {
        payload.append('zip_file', form.zip_file)
      }
      await updateSkill(form.name, payload)
      router.push(`/admin/skills/${form.name}`)
    } else {
      payload.append('name', form.name.trim())
      if (!form.zip_file) {
        throw new Error('请上传 ZIP 压缩包')
      }
      payload.append('zip_file', form.zip_file)
      const createdSkill = await createSkill(payload)
      router.push(`/admin/skills/${createdSkill.name}`)
    }
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
          <p v-if="isEditMode && currentVersion" class="admin-panel__version">
            当前版本：<span class="version-chip">{{ currentVersion }}</span>
            保存后将自动升级到下一个版本。
          </p>
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
            <span>贡献者（可选）</span>
            <input
              v-model="form.contributor"
              class="text-input"
              type="text"
              placeholder="例如：张三 / 平台研发组"
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
            <span>{{ isEditMode ? '升级 ZIP 包（可选）' : 'ZIP 包（必传）' }}</span>
            <input class="file-input" type="file" accept=".zip" @change="onFileChange" />
            <small v-if="selectedFileName">{{ selectedFileName }}</small>
            <small v-else-if="isEditMode">不上传 ZIP 时，将沿用上一版本的安装包。</small>
          </label>

          <p v-if="error" class="feedback feedback--error">{{ error }}</p>

          <div class="form-actions">
            <button class="button" :disabled="submitting" type="submit">
              {{ submitting ? '提交中...' : isEditMode ? '保存并升级' : '创建 Skill' }}
            </button>
            <router-link class="button button--ghost" :to="isEditMode ? `/admin/skills/${form.name}` : '/admin'">
              {{ isEditMode ? '返回详情' : '返回列表' }}
            </router-link>
          </div>
        </form>
      </section>
    </main>
  </div>
</template>
