<!--
THESIS: API Key 是自动化凭证，不把它伪装成普通账号设置，也不让明文长期停留。
OWN-WORLD: 继承工作台暖色画布与克制边框，珊瑚色只用于主操作和复制。
STORY: 用户确认当前状态，创建或轮转一次，在关闭弹窗前复制并安全保存完整 Key。
FIRST VIEWPORT: 当前状态、掩码和唯一主操作处于同一可扫读区域。
FORM: 现有工作台的窄范围扩展，采用操作型单面板结构；无需独立概念种子。
-->
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import ConfirmDialog from '../ConfirmDialog.vue'
import InfoModal from '../InfoModal.vue'
import { buildAbsoluteUrl, createApiKey, fetchApiKeyStatus, rotateApiKey } from '../../services/api'
import { notifyError, notifySuccess } from '../../services/feedback'

const statusPayload = ref(null)
const loading = ref(true)
const actionBusy = ref(false)
const actionError = ref('')
const pendingAction = ref('')
const revealedKey = ref('')
const copiedTarget = ref('')
let copyResetTimer = null

const hasApiKey = computed(() => Boolean(statusPayload.value?.has_api_key))
const maskedKey = computed(() => statusPayload.value?.masked_key || '尚未创建')
const issuedAtLabel = computed(() => formatDate(statusPayload.value?.issued_at))
const openApiDocsUrl = buildAbsoluteUrl('/docs')
const restAuthHeader = 'Authorization: Bearer ns-...'
const confirmation = computed(() => {
  if (pendingAction.value === 'rotate') {
    return {
      title: '确认轮转 API Key？',
      summary: '旧 Key 会立即失效，使用它的自动化任务将停止工作。',
      confirmLabel: '确认轮转',
      tone: 'danger',
    }
  }
  return {
    title: '确认创建 API Key？',
    summary: '系统只会返回一次完整 Key，关闭明文弹窗后无法再次查看。',
    confirmLabel: '创建 API Key',
    tone: 'primary',
  }
})

function formatDate(value) {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

async function loadStatus() {
  loading.value = true
  actionError.value = ''
  try {
    statusPayload.value = await fetchApiKeyStatus()
  } catch (error) {
    actionError.value = error.message || 'API Key 状态加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function requestCreate() {
  actionError.value = ''
  pendingAction.value = 'create'
}

function requestRotate() {
  actionError.value = ''
  pendingAction.value = 'rotate'
}

function closeConfirmation() {
  if (!actionBusy.value) {
    pendingAction.value = ''
  }
}

async function confirmAction() {
  if (!pendingAction.value || actionBusy.value) {
    return
  }

  const action = pendingAction.value
  actionBusy.value = true
  actionError.value = ''
  try {
    const payload = action === 'rotate' ? await rotateApiKey() : await createApiKey()
    statusPayload.value = {
      has_api_key: true,
      masked_key: payload.masked_key,
      issued_at: payload.issued_at,
    }
    revealedKey.value = payload.api_key
    pendingAction.value = ''
    notifySuccess(action === 'rotate' ? 'API Key 已轮转' : 'API Key 已创建')
  } catch (error) {
    actionError.value = error.message || 'API Key 操作失败，请稍后重试。'
  } finally {
    actionBusy.value = false
  }
}

function fallbackCopy(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    if (!document.execCommand('copy')) {
      throw new Error('浏览器拒绝复制')
    }
  } finally {
    document.body.removeChild(textarea)
  }
}

function resetCopiedTarget() {
  window.clearTimeout(copyResetTimer)
  copyResetTimer = window.setTimeout(() => {
    copiedTarget.value = ''
  }, 1800)
}

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // 兼容非安全上下文或浏览器拒绝 Clipboard API 的场景。
    }
  }
  fallbackCopy(text)
}

async function copyText(text, target, successMessage, failureMessage) {
  if (!text) {
    return false
  }
  try {
    await writeClipboardText(text)
  } catch {
    copiedTarget.value = ''
    notifyError(failureMessage)
    return false
  }

  copiedTarget.value = target
  resetCopiedTarget()
  notifySuccess(successMessage)
  return true
}

async function copyApiKey() {
  if (!revealedKey.value) {
    return
  }
  await copyText(
    revealedKey.value,
    'api-key',
    'API Key 已复制',
    '复制失败，请手动选择完整 Key 复制。',
  )
}

function clearRevealedKey() {
  revealedKey.value = ''
  if (copiedTarget.value === 'api-key') {
    copiedTarget.value = ''
  }
}

onMounted(loadStatus)
onBeforeUnmount(() => {
  clearRevealedKey()
  window.clearTimeout(copyResetTimer)
})
</script>

<template>
  <div class="api-key-workbench">
    <section class="operations-panel api-key-operations-panel">
      <div class="operations-panel__copy">
        <h1>自动化访问凭证</h1>
        <p>用于下载可见凭证，以及查询、创建、更新和删除 Skill 与 Skill 集合。</p>
      </div>
    </section>

    <section class="api-key-panel" aria-labelledby="api-key-panel-title" :aria-busy="loading || actionBusy">
      <div class="api-key-panel__heading">
        <div>
          <h2 id="api-key-panel-title">当前 API Key</h2>
          <p>系统只保存不可逆摘要。已有 Key 的完整内容无法再次查看。</p>
        </div>
        <span class="status-chip" :class="hasApiKey ? 'status-chip--active' : ''">
          {{ hasApiKey ? '已创建' : '未创建' }}
        </span>
      </div>

      <p v-if="loading" class="feedback" role="status">正在读取 API Key 状态...</p>

      <template v-else>
        <dl class="api-key-metadata">
          <div>
            <dt>掩码</dt>
            <dd><code>{{ maskedKey }}</code></dd>
          </div>
          <div>
            <dt>签发时间</dt>
            <dd>{{ issuedAtLabel }}</dd>
          </div>
          <div>
            <dt>认证方式</dt>
            <dd><code>Authorization: Bearer ns-...</code></dd>
          </div>
        </dl>

        <div class="api-key-panel__action">
          <div>
            <strong>{{ hasApiKey ? '轮转会立即替换当前 Key' : '首次创建后请立即保存' }}</strong>
            <p>
              {{ hasApiKey
                ? '先更新所有自动化任务，再关闭一次性明文弹窗。旧 Key 在轮转成功后不再可用。'
                : '完整 Key 只在创建成功的响应中出现一次，关闭弹窗后无法恢复。' }}
            </p>
          </div>
          <button
            class="button"
            :class="hasApiKey ? 'button--danger' : ''"
            type="button"
            :disabled="actionBusy"
            @click="hasApiKey ? requestRotate() : requestCreate()"
          >
            {{ hasApiKey ? '轮转 API Key' : '创建 API Key' }}
          </button>
        </div>

        <p v-if="actionError" class="feedback feedback--error" role="alert">
          {{ actionError }}
          <button v-if="!statusPayload" class="button button--ghost button--compact" type="button" @click="loadStatus">
            重新加载
          </button>
        </p>
      </template>
    </section>

    <section class="api-key-docs" aria-labelledby="api-key-docs-title">
      <div class="api-key-docs__heading">
        <div>
          <h2 id="api-key-docs-title">接口与客户端接入</h2>
          <p>当前部署的 REST/OpenAPI 文档集中在这里，复制后只需替换 API Key 占位符。</p>
        </div>
      </div>

      <div class="api-key-docs__grid">
        <article class="api-key-doc-card" aria-labelledby="api-key-openapi-title">
          <header class="api-key-doc-card__header">
            <div>
              <h3 id="api-key-openapi-title">OpenAPI / REST</h3>
              <p>查看接口目录、请求参数和每个路由的认证要求。</p>
            </div>
            <span class="api-key-doc-card__tag">REST</span>
          </header>

          <div class="api-key-doc-links">
            <div class="api-key-doc-link">
              <div class="api-key-doc-link__copy">
                <span class="api-key-doc-link__label">交互式文档</span>
                <a
                  class="api-key-doc-link__url"
                  :href="openApiDocsUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ openApiDocsUrl }}
                </a>
              </div>
              <button
                class="button button--ghost button--compact"
                type="button"
                :aria-label="copiedTarget === 'openapi-docs' ? '已复制 Swagger UI 地址' : '复制 Swagger UI 地址'"
                @click="copyText(openApiDocsUrl, 'openapi-docs', 'Swagger UI 地址已复制', '复制失败，请手动选择地址复制。')"
              >
                {{ copiedTarget === 'openapi-docs' ? '已复制' : '复制地址' }}
              </button>
            </div>
          </div>

          <div class="api-key-doc-note">
            <span class="api-key-doc-note__label">资源接口认证 Header</span>
            <code>{{ restAuthHeader }}</code>
            <p>API Key 只适用于支持资源凭证的接口；登录、Key 生命周期和管理类接口仍遵循各自的登录令牌或权限要求。</p>
          </div>
        </article>
      </div>
    </section>

    <ConfirmDialog
      :open="Boolean(pendingAction)"
      :title="confirmation.title"
      :summary="confirmation.summary"
      :confirm-label="confirmation.confirmLabel"
      :tone="confirmation.tone"
      :busy="actionBusy"
      variant="api-key"
      width="520px"
      @close="closeConfirmation"
      @confirm="confirmAction"
    >
      <div
        class="api-key-confirmation-copy"
        :class="{ 'api-key-confirmation-copy--danger': pendingAction === 'rotate' }"
        role="note"
      >
        <strong>{{ pendingAction === 'rotate' ? '轮转不可撤销' : '先准备安全的保存位置' }}</strong>
        <p>
          {{ pendingAction === 'rotate'
            ? '确认前，请先暂停依赖旧 Key 的任务。系统不会保留旧 Key。'
            : '创建后，页面常驻区域只显示掩码和签发时间。' }}
        </p>
      </div>
      <p v-if="actionError" class="feedback feedback--error feedback--inline" role="alert">{{ actionError }}</p>
    </ConfirmDialog>

    <InfoModal
      :open="Boolean(revealedKey)"
      title="API Key 已生成"
      summary="请复制并安全保存，关闭后将无法再次查看。"
      width="620px"
      variant="api-key"
      @close="clearRevealedKey"
    >
      <div class="api-key-secret">
        <div class="api-key-secret__row">
          <code class="api-key-secret__value">{{ revealedKey }}</code>
          <button
            class="button api-key-secret__copy"
            type="button"
            :aria-label="copiedTarget === 'api-key' ? '已复制 API Key' : '复制 API Key'"
            @click="copyApiKey"
          >
            {{ copiedTarget === 'api-key' ? '已复制' : '复制' }}
          </button>
        </div>
      </div>
      <button class="button button--ghost api-key-secret__close" type="button" @click="clearRevealedKey">
        已保存，关闭
      </button>
    </InfoModal>
  </div>
</template>
