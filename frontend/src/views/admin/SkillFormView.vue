<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { authState, createSkill, fetchGroupOptions, fetchOrganizationOptions, fetchWorkspaceSkill, updateSkill } from '../../services/api'

const skillNamePattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const route = useRoute()
const router = useRouter()
const isEditMode = computed(() => Boolean(route.params.name))
const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const selectedFileName = ref('')
const fileError = ref('')
const currentVersion = ref('')
const showZipGuidance = ref(false)
const groupOptionsLoading = ref(false)
const groupOptionsError = ref('')
const groupOptions = ref([])
const organizationOptionsLoading = ref(false)
const organizationOptionsError = ref('')
const organizationOptions = ref([])
const scopeOptions = [
  { value: 'PUBLIC', label: '公开可见' },
  { value: 'GROUP', label: '归属组可见' },
  { value: 'ORGANIZATION', label: '归属组织可见' },
]
const form = reactive({
  name: '',
  contributor: '',
  description_markdown: '',
  scope_type: 'PUBLIC',
  group_id: '',
  scope_org_level: '',
  scope_org_name: '',
  scope_org_path: '',
  zip_file: null,
})

const selectedOrganization = computed(() =>
  organizationOptions.value.find((item) => item.path === form.scope_org_path) || null,
)
const selectedScopeOption = computed(() =>
  scopeOptions.find((option) => option.value === form.scope_type) || scopeOptions[0],
)
const selectedScopeHelp = computed(() => {
  if (form.scope_type === 'GROUP') {
    return '仅所选组成员和管理员可见。'
  }
  if (form.scope_type === 'ORGANIZATION') {
    return '所选组织及子组织成员可见。'
  }
  return '所有已登录用户均可发现。'
})
const isNameReady = computed(() => {
  const normalizedName = form.name.trim()
  return Boolean(normalizedName && skillNamePattern.test(normalizedName))
})
const isScopeReady = computed(() => {
  if (form.scope_type === 'GROUP') {
    return Boolean(form.group_id)
  }
  if (form.scope_type === 'ORGANIZATION') {
    return Boolean(form.scope_org_path)
  }
  return true
})
const formChecklist = computed(() => [
  {
    key: 'package',
    label: isEditMode.value ? '升级包可选' : 'ZIP 包',
    done: isEditMode.value || Boolean(form.zip_file),
  },
  {
    key: 'identity',
    label: '名称合法',
    done: isNameReady.value,
  },
  {
    key: 'scope',
    label: selectedScopeOption.value.label,
    done: isScopeReady.value,
  },
  {
    key: 'description',
    label: '描述已填写',
    done: Boolean(form.description_markdown.trim()),
  },
])
const submitHint = computed(() => {
  if (submitting.value) {
    return '正在提交，请保持页面打开。'
  }
  if (isEditMode.value) {
    return form.zip_file ? '保存后会生成新版本。' : '未选择 ZIP 时只更新描述和范围。'
  }
  return '创建成功后会进入 Skill 详情页。'
})

function onFileChange(event) {
  const [file] = event.target.files || []
  fileError.value = ''
  form.zip_file = file || null
  selectedFileName.value = file?.name || ''
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    fileError.value = '请上传 ZIP 压缩包'
    form.zip_file = null
  }
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

function mergeGroupOption(option) {
  if (!option || option.id == null) {
    return
  }
  if (groupOptions.value.some((item) => item.id === option.id)) {
    return
  }
  groupOptions.value = [...groupOptions.value, option]
}

async function loadGroupOptions() {
  groupOptionsLoading.value = true
  groupOptionsError.value = ''
  try {
    const existingOptions = [...groupOptions.value]
    groupOptions.value = await fetchGroupOptions()
    existingOptions.forEach(mergeGroupOption)
  } catch (err) {
    groupOptionsError.value = err.message
  } finally {
    groupOptionsLoading.value = false
  }
}

async function loadOrganizationOptions() {
  organizationOptionsLoading.value = true
  organizationOptionsError.value = ''
  try {
    organizationOptions.value = await fetchOrganizationOptions()
  } catch (err) {
    organizationOptionsError.value = err.message
  } finally {
    organizationOptionsLoading.value = false
  }
}

function syncOrganizationSelection() {
  form.scope_org_level = selectedOrganization.value ? String(selectedOrganization.value.level) : ''
  form.scope_org_name = selectedOrganization.value?.name || ''
}

function selectScopeType(scopeType) {
  form.scope_type = scopeType
}

function selectGroup(group) {
  form.group_id = String(group.id)
}

function selectOrganization(option) {
  form.scope_org_path = option.path
  form.scope_org_level = String(option.level)
  form.scope_org_name = option.name
}

function resetGroupScope() {
  form.group_id = ''
}

function resetOrganizationScope() {
  form.scope_org_level = ''
  form.scope_org_name = ''
  form.scope_org_path = ''
}

function validateScope() {
  if (form.scope_type === 'GROUP' && !form.group_id) {
    throw new Error('请选择归属组')
  }
  if (form.scope_type === 'ORGANIZATION') {
    syncOrganizationSelection()
    if (!form.scope_org_level || !form.scope_org_name || !form.scope_org_path) {
      throw new Error('请选择归属组织')
    }
  }
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
    form.scope_type = skill.scope_type || (skill.group_id ? 'GROUP' : 'PUBLIC')
    form.group_id = skill.group_id ? String(skill.group_id) : ''
    form.scope_org_level = skill.scope_org_level ? String(skill.scope_org_level) : ''
    form.scope_org_name = skill.scope_org_name || ''
    form.scope_org_path = skill.scope_org_path || ''
    currentVersion.value = skill.current_version
    if (skill.group_id) {
      mergeGroupOption({
        id: skill.group_id,
        name: skill.group_name || `组 #${skill.group_id}`,
        description: null,
        leader_user_id: null,
        leader_username: '',
      })
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  submitting.value = true
  error.value = ''
  fileError.value = ''
  try {
    const payload = new FormData()
    validateScope()
    payload.append('description_markdown', form.description_markdown)
    payload.append('scope_type', form.scope_type || 'PUBLIC')
    payload.append('group_id', form.scope_type === 'GROUP' ? form.group_id : '')
    payload.append('scope_org_level', form.scope_type === 'ORGANIZATION' ? form.scope_org_level : '')
    payload.append('scope_org_name', form.scope_type === 'ORGANIZATION' ? form.scope_org_name : '')
    payload.append('scope_org_path', form.scope_type === 'ORGANIZATION' ? form.scope_org_path : '')
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
        fileError.value = '请上传 ZIP 压缩包'
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
  loadGroupOptions()
  loadOrganizationOptions()
  loadSkill()
})

watch(
  () => form.scope_type,
  (scopeType) => {
    if (scopeType === 'GROUP') {
      resetOrganizationScope()
      return
    }
    if (scopeType === 'ORGANIZATION') {
      resetGroupScope()
      return
    }
    resetGroupScope()
    resetOrganizationScope()
  },
)
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--skill-form">
      <section class="skill-form-shell">
        <aside class="skill-form-rail">
          <div class="skill-form-rail__heading">
            <h1>{{ isEditMode ? '编辑 Skill' : '新增 Skill' }}</h1>
            <span>{{ isAdmin ? '工作台' : '我的 Skill' }}</span>
          </div>

          <ol class="submission-checklist" aria-label="提交检查">
            <li
              v-for="item in formChecklist"
              :key="item.key"
              :class="{ 'is-done': item.done }"
            >
              <span aria-hidden="true">{{ item.done ? '✓' : '·' }}</span>
              <strong>{{ item.label }}</strong>
            </li>
          </ol>

          <p v-if="isEditMode && currentVersion" class="skill-form-rail__version">
            当前版本 <span class="version-chip">{{ currentVersion }}</span>
          </p>
        </aside>

        <section class="skill-form-main">
          <section v-if="loading" class="feedback">正在加载 Skill...</section>

          <form v-else class="skill-form" @submit.prevent="handleSubmit">
            <section class="form-section">
              <div class="section-heading section-heading--inline">
                <div>
                  <h2>{{ isEditMode ? '升级包' : 'ZIP 包' }}</h2>
                  <p>根目录需包含非空 <code>SKILL.md</code>。</p>
                </div>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  :aria-expanded="showZipGuidance ? 'true' : 'false'"
                  aria-controls="zip-package-guidance"
                  @click="toggleZipGuidance"
                >
                  {{ showZipGuidance ? '收起' : '格式' }}
                </button>
              </div>

              <section v-if="showZipGuidance" id="zip-package-guidance" class="zip-guidance" role="note">
                <p class="zip-guidance__title">推荐压缩包根目录</p>
                <pre class="zip-guidance__tree"><code>your-skill.zip
|- SKILL.md</code></pre>
                <ul class="zip-guidance__list">
                  <li>不要把 <code>SKILL.md</code> 放在二级目录。</li>
                </ul>
              </section>

              <label class="upload-dropzone upload-dropzone--large" for="skill-zip-file">
                <input id="skill-zip-file" class="upload-dropzone__input" type="file" accept=".zip" @change="onFileChange" />
                <span class="upload-dropzone__title">
                  {{ selectedFileName || (isEditMode ? '选择新版本包' : '选择 ZIP 包') }}
                </span>
                <span class="upload-dropzone__hint">
                  {{ selectedFileName ? '提交时会上传处理。' : isEditMode ? '不选择则沿用当前版本。' : '支持 .zip 文件。' }}
                </span>
              </label>
              <small v-if="fileError" class="feedback feedback--error feedback--inline">{{ fileError }}</small>
            </section>

            <section class="form-section">
              <div class="section-heading">
                <h2>基本信息</h2>
              </div>
              <div class="form-grid">
                <label class="field">
                  <span>Skill 名称</span>
                  <input
                    v-model="form.name"
                    class="text-input"
                    type="text"
                    :disabled="isEditMode"
                    placeholder="例如：plm-assistant"
                  />
                  <small class="field__hint">仅小写字母、数字和中划线。</small>
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
              </div>
            </section>

            <section class="form-section">
              <div class="section-heading">
                <h2>可见范围</h2>
              </div>

              <div class="scope-picker scope-picker--cards" role="radiogroup" aria-label="可见范围">
                <button
                  v-for="option in scopeOptions"
                  :key="option.value"
                  type="button"
                  class="scope-tag"
                  :class="{ 'scope-tag--active': form.scope_type === option.value }"
                  :aria-checked="form.scope_type === option.value ? 'true' : 'false'"
                  role="radio"
                  @click="selectScopeType(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
              <small class="scope-picker__hint">{{ selectedScopeHelp }}</small>

              <div v-if="form.scope_type === 'GROUP'" class="field scope-target-panel">
                <span>归属组</span>
                <div v-if="groupOptions.length" class="scope-option-list" aria-label="归属组">
                  <button
                    v-for="group in groupOptions"
                    :key="group.id"
                    type="button"
                    class="scope-option-tag"
                    :class="{ 'scope-option-tag--active': form.group_id === String(group.id) }"
                    :disabled="groupOptionsLoading"
                    @click="selectGroup(group)"
                  >
                    {{ group.name }}
                  </button>
                </div>
                <small v-if="groupOptionsLoading">正在加载可选组...</small>
                <small v-else-if="groupOptionsError" class="feedback feedback--error feedback--inline">{{ groupOptionsError }}</small>
                <small v-else-if="!groupOptions.length">当前没有可选组。</small>
              </div>

              <div v-if="form.scope_type === 'ORGANIZATION'" class="field scope-target-panel">
                <span>归属组织</span>
                <div v-if="organizationOptions.length" class="scope-option-list" aria-label="归属组织">
                  <button
                    v-for="option in organizationOptions"
                    :key="option.path"
                    type="button"
                    class="scope-option-tag"
                    :class="{ 'scope-option-tag--active': form.scope_org_path === option.path }"
                    :disabled="organizationOptionsLoading"
                    @click="selectOrganization(option)"
                  >
                    {{ option.path }}{{ option.is_leaf ? '' : '（上级组织）' }}
                  </button>
                </div>
                <small v-if="selectedOrganization">
                  当前选择：{{ selectedOrganization.level }} 级组织 · {{ selectedOrganization.name }}
                </small>
                <small v-if="organizationOptionsLoading">正在加载可选组织...</small>
                <small v-else-if="organizationOptionsError" class="feedback feedback--error feedback--inline">{{ organizationOptionsError }}</small>
                <small v-else-if="!organizationOptions.length">当前没有可选组织，可能该账号尚未同步 AD 组织架构。</small>
              </div>
            </section>

            <section class="form-section">
              <div class="section-heading">
                <h2>描述</h2>
              </div>
              <label class="field">
                <span>Markdown 内容</span>
                <textarea
                  v-model="form.description_markdown"
                  class="text-area text-area--markdown"
                  rows="14"
                  placeholder="写清用途、安装方式和注意事项"
                />
              </label>
            </section>

            <section v-if="error" class="feedback feedback--error">{{ error }}</section>

            <section class="submit-bar">
              <p>{{ submitHint }}</p>
              <div class="form-actions">
                <button class="button" :disabled="submitting" type="submit">
                  {{ submitting ? '提交中...' : isEditMode ? '保存并升级' : '创建 Skill' }}
                </button>
                <router-link class="button button--ghost" :to="isEditMode ? `/workspace/skills/${form.name}` : '/workspace'">
                  {{ isEditMode ? '返回详情' : '返回列表' }}
                </router-link>
              </div>
            </section>
          </form>
        </section>
      </section>
    </main>
  </div>
</template>
