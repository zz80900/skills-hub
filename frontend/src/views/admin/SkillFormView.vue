<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import { authState, createSkill, fetchGroupOptions, fetchOrganizationOptions, fetchWorkspaceSkill, updateSkill } from '../../services/api'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
  skillName: {
    type: String,
    default: '',
  },
})
const emit = defineEmits(['close', 'saved'])
const skillNamePattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const route = useRoute()
const router = useRouter()
const targetSkillName = computed(() => props.skillName || (typeof route.params.name === 'string' ? route.params.name : ''))
const isEditMode = computed(() => Boolean(targetSkillName.value))
const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const fileError = ref('')
const fileInput = ref(null)
const isDraggingFile = ref(false)
const dragDepth = ref(0)
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
const selectedGroup = computed(() =>
  groupOptions.value.find((item) => String(item.id) === form.group_id) || null,
)
const selectedFileName = computed(() => form.zip_file?.name || '')
const selectedFileSize = computed(() => form.zip_file ? formatFileSize(form.zip_file.size) : '')
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
const scopeSummary = computed(() => {
  if (form.scope_type === 'GROUP') {
    return selectedGroup.value
      ? `归属组可见 · ${selectedGroup.value.name}`
      : '归属组可见 · 待选择归属组'
  }
  if (form.scope_type === 'ORGANIZATION') {
    const organizationLabel = form.scope_org_path || form.scope_org_name
    return organizationLabel
      ? `归属组织可见 · ${organizationLabel}`
      : '归属组织可见 · 待选择归属组织'
  }
  return '公开可见'
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

function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  const units = ['KB', 'MB', 'GB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)) - 1, units.length - 1)
  const value = bytes / (1024 ** (unitIndex + 1))
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}

function setFileError(message) {
  fileError.value = form.zip_file ? `${message}，原文件已保留。` : message
}

function receiveZipFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length) {
    return false
  }
  if (files.length !== 1) {
    setFileError('一次只能上传一个 ZIP 压缩包')
    return false
  }

  const [file] = files
  if (!file.name.toLowerCase().endsWith('.zip')) {
    setFileError('只支持 ZIP 压缩包')
    return false
  }
  if (file.size === 0) {
    setFileError('ZIP 文件不能为空')
    return false
  }

  form.zip_file = file
  fileError.value = ''
  return true
}

function resetNativeFileInput() {
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

function onFileChange(event) {
  receiveZipFiles(event.target.files)
  resetNativeFileInput()
}

function onFileDragEnter(event) {
  if (!Array.from(event.dataTransfer?.types || []).includes('Files')) {
    return
  }
  dragDepth.value += 1
  isDraggingFile.value = true
}

function onFileDragOver(event) {
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function onFileDragLeave() {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
  if (dragDepth.value === 0) {
    isDraggingFile.value = false
  }
}

function onFileDrop(event) {
  dragDepth.value = 0
  isDraggingFile.value = false
  receiveZipFiles(event.dataTransfer?.files)
}

function replaceSelectedFile() {
  fileInput.value?.click()
}

function removeSelectedFile() {
  form.zip_file = null
  fileError.value = ''
  dragDepth.value = 0
  isDraggingFile.value = false
  resetNativeFileInput()
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
    const skill = await fetchWorkspaceSkill(targetSkillName.value)
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
      if (props.embedded) {
        emit('saved', { name: validatedName })
      } else {
        router.push(`/workspace/skills/${validatedName}`)
      }
    } else {
      payload.append('name', validatedName)
      if (!form.zip_file) {
        fileError.value = '请上传 ZIP 压缩包'
        throw new Error('请上传 ZIP 压缩包')
      }
      payload.append('zip_file', form.zip_file)
      const createdSkill = await createSkill(payload)
      if (props.embedded) {
        emit('saved', { name: createdSkill.name })
      } else {
        router.push(`/workspace/skills/${createdSkill.name}`)
      }
    }
  } catch (err) {
    if (!fileError.value || fileError.value !== err.message) {
      error.value = err.message
    }
  } finally {
    submitting.value = false
  }
}

function closeForm() {
  emit('close')
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
  <div class="page-shell" :class="{ 'page-shell--embedded': embedded }">
    <SiteHeader v-if="!embedded" />
    <main class="page-content page-content--skill-form" :class="{ 'page-content--embedded': embedded }">
      <section class="skill-form-shell" :class="{ 'skill-form-shell--embedded': embedded }">
        <aside v-if="!embedded" class="skill-form-rail">
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
                  <p>根目录需包含非空 <code>SKILL.md</code>，<code>cmd</code> 只作为普通文件保存。</p>
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
|- SKILL.md
\- cmd        # 可选，普通文本文件</code></pre>
                <ul class="zip-guidance__list">
                  <li>不要把 <code>SKILL.md</code> 放在二级目录。</li>
                  <li><code>cmd</code> 不会被服务端或 CLI 解析、校验或执行。</li>
                </ul>
              </section>

              <div
                class="upload-dropzone upload-dropzone--large"
                :class="{
                  'upload-dropzone--dragging': isDraggingFile,
                  'upload-dropzone--selected': selectedFileName,
                }"
                @dragenter.prevent="onFileDragEnter"
                @dragover.prevent="onFileDragOver"
                @dragleave.prevent="onFileDragLeave"
                @drop.prevent="onFileDrop"
              >
                <input
                  id="skill-zip-file"
                  ref="fileInput"
                  class="upload-dropzone__input"
                  type="file"
                  accept=".zip"
                  :aria-invalid="fileError ? 'true' : 'false'"
                  aria-describedby="skill-zip-help skill-zip-error"
                  @change="onFileChange"
                />
                <label class="upload-dropzone__trigger" for="skill-zip-file">
                  <span class="upload-dropzone__indicator" aria-hidden="true">
                    {{ isDraggingFile ? '↓' : selectedFileName ? '✓' : 'ZIP' }}
                  </span>
                  <span class="upload-dropzone__copy">
                    <span class="upload-dropzone__title">
                      {{ isDraggingFile ? '释放以上传' : selectedFileName ? '替换当前 ZIP' : isEditMode ? '选择新版本包' : '选择 ZIP 包' }}
                    </span>
                    <span id="skill-zip-help" class="upload-dropzone__hint">
                      {{ isDraggingFile ? '仅接收一个非空 .zip 文件。' : selectedFileName ? '点击或拖入另一个 ZIP 进行替换。' : isEditMode ? '点击选择或拖入文件；不选择则沿用当前版本。' : '点击选择或拖入一个非空 .zip 文件。' }}
                    </span>
                  </span>
                </label>

                <div v-if="selectedFileName" class="upload-dropzone__selected-file" role="status" aria-live="polite">
                  <span class="upload-dropzone__success" aria-hidden="true">✓</span>
                  <span class="upload-dropzone__file-copy">
                    <strong>{{ selectedFileName }}</strong>
                    <small>{{ selectedFileSize }} · {{ isEditMode ? '保存后生成新版本' : '创建时随表单上传' }}</small>
                  </span>
                  <span class="upload-dropzone__actions">
                    <button class="button button--ghost button--compact" type="button" @click="replaceSelectedFile">替换</button>
                    <button class="button button--ghost button--compact upload-dropzone__remove" type="button" @click="removeSelectedFile">移除</button>
                  </span>
                </div>
              </div>
              <small
                v-if="fileError"
                id="skill-zip-error"
                class="feedback feedback--error feedback--inline"
                role="alert"
              >{{ fileError }}</small>
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
                  <span class="scope-selection-mark" aria-hidden="true">✓</span>
                  <span>{{ option.label }}</span>
                </button>
              </div>
              <small class="scope-picker__hint">{{ selectedScopeHelp }}</small>
              <div class="scope-summary" role="status" aria-live="polite" aria-atomic="true">
                <span class="scope-summary__label">当前可见范围</span>
                <strong class="scope-summary__value">{{ scopeSummary }}</strong>
              </div>

              <div v-if="form.scope_type === 'GROUP'" class="field scope-target-panel">
                <span>归属组</span>
                <div v-if="groupOptions.length" class="scope-option-list" role="radiogroup" aria-label="归属组">
                  <button
                    v-for="group in groupOptions"
                    :key="group.id"
                    type="button"
                    class="scope-option-tag"
                    :class="{ 'scope-option-tag--active': form.group_id === String(group.id) }"
                    :aria-checked="form.group_id === String(group.id) ? 'true' : 'false'"
                    role="radio"
                    :disabled="groupOptionsLoading"
                    @click="selectGroup(group)"
                  >
                    <span class="scope-selection-mark" aria-hidden="true">✓</span>
                    <span class="scope-option-label">{{ group.name }}</span>
                  </button>
                </div>
                <small v-if="groupOptionsLoading">正在加载可选组...</small>
                <small v-else-if="groupOptionsError" class="feedback feedback--error feedback--inline">{{ groupOptionsError }}</small>
                <small v-else-if="!groupOptions.length">当前没有可选组。</small>
              </div>

              <div v-if="form.scope_type === 'ORGANIZATION'" class="field scope-target-panel">
                <span>归属组织</span>
                <div v-if="organizationOptions.length" class="scope-option-list" role="radiogroup" aria-label="归属组织">
                  <button
                    v-for="option in organizationOptions"
                    :key="option.path"
                    type="button"
                    class="scope-option-tag"
                    :class="{ 'scope-option-tag--active': form.scope_org_path === option.path }"
                    :aria-checked="form.scope_org_path === option.path ? 'true' : 'false'"
                    role="radio"
                    :disabled="organizationOptionsLoading"
                    @click="selectOrganization(option)"
                  >
                    <span class="scope-selection-mark" aria-hidden="true">✓</span>
                    <span class="scope-option-label">{{ option.path }}{{ option.is_leaf ? '' : '（上级组织）' }}</span>
                  </button>
                </div>
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
                <button v-if="embedded" class="button button--ghost" type="button" @click="closeForm">
                  取消
                </button>
                <router-link v-else class="button button--ghost" :to="isEditMode ? `/workspace/skills/${form.name}` : '/workspace'">
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
