<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { authState, createSkill, fetchWorkspaceSkill, updateSkill } from '../../services/api'

const skillNamePattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const route = useRoute()
const router = useRouter()
const isEditMode = computed(() => Boolean(route.params.name))
const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const selectedFileName = ref('')
const currentVersion = ref('')
const showZipGuidance = ref(false)
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

function toggleZipGuidance() {
  showZipGuidance.value = !showZipGuidance.value
}

function validateSkillName(name) {
  const normalizedName = (name || '').trim()
  if (!normalizedName) {
    throw new Error('请输入 Skill 名称')
  }
  if (/\s/.test(normalizedName)) {
    throw new Error('Skill 名称不能包含空格')
  }
  if (!skillNamePattern.test(normalizedName)) {
    throw new Error('Skill 名称只允许小写字母、数字和中划线')
  }
  return normalizedName
}

async function loadSkill() {
  if (!isEditMode.value) {
    return
  }
  loading.value = true
  error.value = ''
  try {
    const skill = await fetchWorkspaceSkill(route.params.name)
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
    payload.append('description_markdown', form.description_markdown)
    const validatedName = validateSkillName(form.name)

    if (isEditMode.value) {
      if (form.zip_file) {
        payload.append('zip_file', form.zip_file)
      }
      await updateSkill(validatedName, payload)
      router.push(`/workspace/skills/${validatedName}`)
    } else {
      payload.append('name', validatedName)
      if (!form.zip_file) {
        throw new Error('请上传 ZIP 压缩包')
      }
      payload.append('zip_file', form.zip_file)
      const createdSkill = await createSkill(payload)
      router.push(`/workspace/skills/${createdSkill.name}`)
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
          <p class="eyebrow">{{ isAdmin ? '工作台' : '我的 Skill' }}</p>
          <h1>{{ isEditMode ? '编辑 / 升级 Skill' : '新增 Skill' }}</h1>
          <p>上传时只支持 ZIP；请在上传字段旁查看压缩包根目录格式要求。</p>
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

          <label v-if="isEditMode" class="field">
            <span>上传者</span>
            <input
              v-model="form.contributor"
              class="text-input"
              type="text"
              disabled
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

          <div class="field">
            <div class="field__label field__label--with-action">
              <label class="field__label-text" for="skill-zip-file">
                {{ isEditMode ? '升级 ZIP 包（可选）' : 'ZIP 包（必传）' }}
              </label>
              <button
                class="field-help__button"
                type="button"
                :aria-expanded="showZipGuidance ? 'true' : 'false'"
                aria-controls="zip-package-guidance"
                @click="toggleZipGuidance"
              >
                <span class="field-help__icon" aria-hidden="true">i</span>
                <span>格式说明</span>
              </button>
            </div>

            <p class="field__hint">根目录必须包含非空 <code>SKILL.md</code>。</p>

            <section v-if="showZipGuidance" id="zip-package-guidance" class="zip-guidance" role="note">
              <p class="zip-guidance__title">推荐压缩包根目录</p>
              <pre class="zip-guidance__tree"><code>your-skill.zip
|- SKILL.md
\- cmd        # 可选，仅当需要额外安装 CLI</code></pre>
              <ul class="zip-guidance__list">
                <li>根目录必须存在非空 <code>SKILL.md</code>。</li>
                <li>如需额外安装 CLI，可在根目录提供一个名为 <code>cmd</code> 的文件。</li>
                <li><code>cmd</code> 只能包含一条以 <code>npm install</code> 开头的命令。</li>
                <li><code>cmd</code> 不能包含其他命令、命令拼接或多行脚本。</li>
              </ul>
            </section>

            <input id="skill-zip-file" class="file-input" type="file" accept=".zip" @change="onFileChange" />
            <small v-if="selectedFileName">{{ selectedFileName }}</small>
            <small v-else-if="isEditMode">不上传 ZIP 时，将沿用上一版本的安装包。</small>
          </div>

          <p v-if="error" class="feedback feedback--error">{{ error }}</p>

          <div class="form-actions">
            <button class="button" :disabled="submitting" type="submit">
              {{ submitting ? '提交中...' : isEditMode ? '保存并升级' : '创建 Skill' }}
            </button>
            <router-link class="button button--ghost" :to="isEditMode ? `/workspace/skills/${form.name}` : '/workspace'">
              {{ isEditMode ? '返回详情' : '返回列表' }}
            </router-link>
          </div>
        </form>
      </section>
    </main>
  </div>
</template>
