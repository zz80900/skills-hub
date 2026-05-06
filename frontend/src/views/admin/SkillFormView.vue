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
            <span>可见范围</span>
            <div class="scope-picker" role="radiogroup" aria-label="可见范围">
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
            <small class="field__hint">
              {{
                form.scope_type === 'GROUP'
                  ? '绑定组后，仅该组成员和管理员可在首页查看。'
                  : form.scope_type === 'ORGANIZATION'
                    ? '绑定组织后，该组织及其子组织成员和管理员可在首页查看。'
                    : '不绑定范围时，Skill 会继续公开展示。'
              }}
            </small>
          </div>

          <div v-if="form.scope_type === 'GROUP'" class="field">
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

          <div v-if="form.scope_type === 'ORGANIZATION'" class="field">
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
