<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import {
  authState,
  createCollection,
  fetchGroupOptions,
  fetchOrganizationOptions,
  fetchWorkspaceCollection,
  previewCollectionZip,
  updateCollection,
} from '../../services/api'

const props = defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
  collectionSlug: {
    type: String,
    default: '',
  },
})
const emit = defineEmits(['close', 'saved'])
const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const route = useRoute()
const router = useRouter()
const targetCollectionSlug = computed(() => props.collectionSlug || (typeof route.params.slug === 'string' ? route.params.slug : ''))
const isEditMode = computed(() => Boolean(targetCollectionSlug.value))
const isAdmin = computed(() => authState.user?.role === 'ADMIN')
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const selectedFileName = ref('')
const fileError = ref('')
const currentVersion = ref('')
const showZipGuidance = ref(false)
const preview = ref(null)
const previewLoading = ref(false)
const previewError = ref('')
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
  slug: '',
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
  return '所有访客都可发现。'
})
const isSlugReady = computed(() => {
  const normalizedSlug = form.slug.trim()
  return Boolean(normalizedSlug && slugPattern.test(normalizedSlug))
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
    label: isEditMode.value ? '升级包可选' : 'Skill 集合 ZIP',
    done: isEditMode.value || Boolean(form.zip_file),
  },
  {
    key: 'slug',
    label: 'slug 合法',
    done: isSlugReady.value,
  },
  {
    key: 'scope',
    label: selectedScopeOption.value.label,
    done: isScopeReady.value,
  },
  {
    key: 'preview',
    label: preview.value ? `${preview.value.item_count} 个 Skill` : '等待预览',
    done: Boolean(preview.value) || isEditMode.value,
  },
])
const nextPreviewVersion = computed(() => {
  if (!isEditMode.value) {
    return '1.0.0'
  }
  return getNextVersion(currentVersion.value)
})
const submitHint = computed(() => {
  if (submitting.value) {
    return '正在提交，请保持页面打开。'
  }
  if (isEditMode.value) {
    return form.zip_file ? '保存后会生成新 Skill 集合版本。' : '未选择 ZIP 时只更新元数据和范围。'
  }
  return '创建成功后会进入 Skill 集合详情页。'
})

function getNextVersion(version) {
  const match = /^([0-9])\.([0-9])\.([0-9])$/.exec(version || '')
  if (!match) {
    return '-'
  }
  let major = Number(match[1])
  let minor = Number(match[2])
  let patch = Number(match[3])
  if (major === 9 && minor === 9 && patch === 9) {
    return '已达上限'
  }
  if (patch < 9) {
    patch += 1
  } else {
    patch = 0
    if (minor < 9) {
      minor += 1
    } else {
      minor = 0
      major += 1
    }
  }
  return `${major}.${minor}.${patch}`
}

function validateSlug(slug) {
  const normalizedSlug = (slug || '').trim()
  if (!normalizedSlug) {
    throw new Error('请输入 Skill 集合 slug')
  }
  if (/\s/.test(normalizedSlug)) {
    throw new Error('Skill 集合 slug 不能包含空格')
  }
  if (!slugPattern.test(normalizedSlug)) {
    throw new Error('Skill 集合 slug 只允许小写字母、数字和中划线')
  }
  return normalizedSlug
}

function validateName(name) {
  const normalizedName = (name || '').trim()
  if (!normalizedName) {
    throw new Error('请输入 Skill 集合名称')
  }
  return normalizedName
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

async function loadPreview() {
  preview.value = null
  previewError.value = ''
  if (!form.zip_file) {
    return
  }
  previewLoading.value = true
  try {
    const payload = new FormData()
    payload.append('zip_file', form.zip_file)
    preview.value = await previewCollectionZip(payload)
  } catch (err) {
    previewError.value = err.message
  } finally {
    previewLoading.value = false
  }
}

function onFileChange(event) {
  const [file] = event.target.files || []
  fileError.value = ''
  preview.value = null
  previewError.value = ''
  form.zip_file = file || null
  selectedFileName.value = file?.name || ''
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    fileError.value = '请上传 ZIP 压缩包'
    form.zip_file = null
    return
  }
  loadPreview()
}

function toggleZipGuidance() {
  showZipGuidance.value = !showZipGuidance.value
}

async function loadCollection() {
  if (!isEditMode.value) {
    return
  }
  loading.value = true
  error.value = ''
  try {
    const collection = await fetchWorkspaceCollection(targetCollectionSlug.value)
    form.name = collection.name
    form.slug = collection.slug
    form.description_markdown = collection.description_markdown
    form.scope_type = collection.scope_type || (collection.group_id ? 'GROUP' : 'PUBLIC')
    form.group_id = collection.group_id ? String(collection.group_id) : ''
    form.scope_org_level = collection.scope_org_level ? String(collection.scope_org_level) : ''
    form.scope_org_name = collection.scope_org_name || ''
    form.scope_org_path = collection.scope_org_path || ''
    currentVersion.value = collection.current_version
    if (collection.group_id) {
      mergeGroupOption({
        id: collection.group_id,
        name: collection.group_name || `组 #${collection.group_id}`,
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
    const validatedName = validateName(form.name)
    const validatedSlug = validateSlug(form.slug)
    payload.append('name', validatedName)
    payload.append('description_markdown', form.description_markdown)
    payload.append('scope_type', form.scope_type || 'PUBLIC')
    payload.append('group_id', form.scope_type === 'GROUP' ? form.group_id : '')
    payload.append('scope_org_level', form.scope_type === 'ORGANIZATION' ? form.scope_org_level : '')
    payload.append('scope_org_name', form.scope_type === 'ORGANIZATION' ? form.scope_org_name : '')
    payload.append('scope_org_path', form.scope_type === 'ORGANIZATION' ? form.scope_org_path : '')

    if (isEditMode.value) {
      if (form.zip_file) {
        payload.append('zip_file', form.zip_file)
      }
      await updateCollection(targetCollectionSlug.value, payload)
      if (props.embedded) {
        emit('saved', { slug: validatedSlug })
      } else {
        router.push(`/workspace/collections/${validatedSlug}`)
      }
    } else {
      payload.append('slug', validatedSlug)
      if (!form.zip_file) {
        fileError.value = '请上传 Skill 集合 ZIP'
        throw new Error('请上传 Skill 集合 ZIP')
      }
      payload.append('zip_file', form.zip_file)
      const createdCollection = await createCollection(payload)
      if (props.embedded) {
        emit('saved', { slug: createdCollection.slug })
      } else {
        router.push(`/workspace/collections/${createdCollection.slug}`)
      }
    }
  } catch (err) {
    error.value = err.message
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
  loadCollection()
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
            <h1>{{ isEditMode ? '编辑 Skill 集合' : '新增 Skill 集合' }}</h1>
            <span>{{ isAdmin ? '工作台' : '我的 Skill 集合' }}</span>
          </div>

          <ol class="submission-checklist" aria-label="提交检查">
            <li v-for="item in formChecklist" :key="item.key" :class="{ 'is-done': item.done }">
              <span aria-hidden="true">{{ item.done ? '✓' : '·' }}</span>
              <strong>{{ item.label }}</strong>
            </li>
          </ol>

          <p v-if="isEditMode && currentVersion" class="skill-form-rail__version">
            当前版本 <span class="version-chip">{{ currentVersion }}</span>
          </p>
        </aside>

        <section class="skill-form-main">
          <section v-if="loading" class="feedback">正在加载 Skill 集合...</section>

          <form v-else class="skill-form" @submit.prevent="handleSubmit">
            <section class="form-section">
              <div class="section-heading section-heading--inline">
                <div>
                  <h2>{{ isEditMode ? '升级包' : 'Skill 集合 ZIP' }}</h2>
                  <p>根目录下每个一级目录都是一个 Skill，目录内需直接包含非空 <code>SKILL.md</code>。</p>
                </div>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  :aria-expanded="showZipGuidance ? 'true' : 'false'"
                  aria-controls="collection-zip-guidance"
                  @click="toggleZipGuidance"
                >
                  {{ showZipGuidance ? '收起' : '格式' }}
                </button>
              </div>

              <section v-if="showZipGuidance" id="collection-zip-guidance" class="zip-guidance" role="note">
                <p class="zip-guidance__title">Skill 集合压缩包根目录</p>
                <pre class="zip-guidance__tree"><code>frontend-basic.zip
|- frontend-design/
|  |- SKILL.md
|  \- references/
\- code-review/
   \- SKILL.md</code></pre>
                <ul class="zip-guidance__list">
                  <li>根目录不要放 <code>README.md</code>、<code>collection.json</code> 或其他普通文件。</li>
                  <li>不需要 <code>skills/</code>、<code>codex/</code> 或 <code>claude-code/</code> 包裹目录。</li>
                </ul>
              </section>

              <label class="upload-dropzone upload-dropzone--large" for="collection-zip-file">
                <input id="collection-zip-file" class="upload-dropzone__input" type="file" accept=".zip" @change="onFileChange" />
                <span class="upload-dropzone__title">
                  {{ selectedFileName || (isEditMode ? '选择新版本 Skill 集合包' : '选择 Skill 集合 ZIP') }}
                </span>
                <span class="upload-dropzone__hint">
                  {{ selectedFileName ? '已选择，正在用于预览和提交。' : isEditMode ? '不选择则只更新元数据。' : '支持 .zip 文件。' }}
                </span>
              </label>
              <small v-if="fileError" class="feedback feedback--error feedback--inline">{{ fileError }}</small>

              <section v-if="previewLoading || preview || previewError" class="collection-preview" aria-live="polite">
                <span v-if="previewLoading">正在解析 Skill 集合 ZIP...</span>
                <template v-else-if="preview">
                  <div class="collection-preview__header">
                    <strong>{{ isEditMode ? '将生成版本' : '初始版本' }} {{ nextPreviewVersion }}</strong>
                    <span>{{ preview.item_count }} 个 Skill</span>
                  </div>
                  <ul class="collection-preview__list">
                    <li v-for="item in preview.items" :key="item.path">
                      <span>{{ item.name }}</span>
                      <code>{{ item.sha256.slice(0, 12) }}</code>
                    </li>
                  </ul>
                </template>
                <span v-else class="feedback--error">{{ previewError }}</span>
              </section>
            </section>

            <section class="form-section form-section--identity">
              <div class="section-heading">
                <h2>基本信息</h2>
              </div>
              <div class="collection-identity-grid">
                <label class="field">
                  <span class="field__label-line">
                    <span class="field__label-text">Skill 集合名称</span>
                  </span>
                  <input v-model="form.name" class="text-input" type="text" placeholder="例如：前端基础工作流" />
                </label>

                <label class="field">
                  <span class="field__label-line">
                    <span class="field__label-text">Skill 集合 slug</span>
                    <small id="collection-slug-hint" class="field__hint field__hint--inline">仅小写字母、数字和中划线</small>
                  </span>
                  <input
                    v-model="form.slug"
                    class="text-input"
                    type="text"
                    :disabled="isEditMode"
                    aria-describedby="collection-slug-hint"
                    placeholder="例如：frontend-basic"
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
                  placeholder="写清 Skill 集合用途、包含的 Skill 和适用场景"
                />
              </label>
            </section>

            <section v-if="error" class="feedback feedback--error">{{ error }}</section>

            <section class="submit-bar">
              <p>{{ submitHint }}</p>
              <div class="form-actions">
                <button class="button" :disabled="submitting" type="submit">
                  {{ submitting ? '提交中...' : isEditMode ? '保存 Skill 集合' : '创建 Skill 集合' }}
                </button>
                <button v-if="embedded" class="button button--ghost" type="button" @click="closeForm">
                  取消
                </button>
                <router-link v-else class="button button--ghost" :to="isEditMode ? `/workspace/collections/${form.slug}` : '/workspace?tab=collections'">
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
