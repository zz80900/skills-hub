<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import CommandSnippet from './CommandSnippet.vue'

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
  skill: {
    type: Object,
    default: null,
  },
  source: {
    type: String,
    default: 'local',
  },
  selectedVersion: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['close', 'version-select'])

const effectiveVersion = computed(() => props.selectedVersion || props.skill?.version || '')
const historyVersions = computed(() => props.skill?.history_versions || [])
const canSelectHistory = computed(() => props.source === 'local' && historyVersions.value.length > 0)
const isVersionMenuOpen = ref(false)
const versionMenuRef = ref(null)

function closeModal() {
  emit('close')
}

function closeVersionMenu() {
  isVersionMenuOpen.value = false
}

function toggleVersionMenu() {
  isVersionMenuOpen.value = !isVersionMenuOpen.value
}

function selectVersion(version) {
  if (version !== effectiveVersion.value) {
    emit('version-select', version)
  }
  closeVersionMenu()
}

function handleBackdropClick(event) {
  if (event.target === event.currentTarget) {
    closeModal()
  }
}

function handleDocumentClick(event) {
  if (!versionMenuRef.value?.contains(event.target)) {
    closeVersionMenu()
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    if (isVersionMenuOpen.value) {
      closeVersionMenu()
      return
    }
    closeModal()
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      window.addEventListener('keydown', handleKeydown)
      window.addEventListener('pointerdown', handleDocumentClick)
      document.body.style.overflow = 'hidden'
      return
    }
    window.removeEventListener('keydown', handleKeydown)
    window.removeEventListener('pointerdown', handleDocumentClick)
    document.body.style.overflow = ''
    closeVersionMenu()
  },
  { immediate: true },
)

watch(
  () => props.selectedVersion,
  () => {
    closeVersionMenu()
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('pointerdown', handleDocumentClick)
  document.body.style.overflow = ''
})
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div v-if="open" class="detail-modal" @click="handleBackdropClick">
        <div class="detail-modal__dialog" role="dialog" aria-modal="true">
          <button class="detail-modal__close" type="button" aria-label="关闭详情" @click="closeModal">
            关闭
          </button>

          <section v-if="loading" class="feedback detail-modal__feedback">正在加载 Skill 详情...</section>
          <section v-else-if="error" class="feedback feedback--error detail-modal__feedback">{{ error }}</section>
          <template v-else-if="skill">
            <div class="detail-modal__header">
              <div>
                <p class="eyebrow">Skill 详情</p>
                <h2>{{ skill.name }}</h2>
                <p class="detail-modal__summary">
                  {{ skill.source_label || (source === 'skills_sh' ? 'skills.sh' : '本地库') }}
                </p>
              </div>
            </div>

            <div class="detail-modal__meta">
              <div v-if="source === 'local'" class="detail-meta__item">
                <span>版本号</span>
                <code>{{ skill.version || '未设置' }}</code>
              </div>
              <div v-if="canSelectHistory" class="detail-meta__item">
                <span>历史版本</span>
                <div ref="versionMenuRef" class="detail-meta__select-shell">
                  <span class="detail-meta__version-pill">当前 {{ effectiveVersion }}</span>
                  <div class="detail-meta__select-wrap">
                    <button
                      class="detail-meta__select-trigger"
                      type="button"
                      :aria-expanded="isVersionMenuOpen"
                      aria-haspopup="listbox"
                      @click="toggleVersionMenu"
                    >
                      <span class="detail-meta__select-value">{{ effectiveVersion }}</span>
                      <span class="detail-meta__select-icon" :class="{ 'is-open': isVersionMenuOpen }" aria-hidden="true">
                        <svg viewBox="0 0 20 20" role="presentation">
                          <path
                            d="M5.47 7.97a.75.75 0 0 1 1.06 0L10 11.44l3.47-3.47a.75.75 0 1 1 1.06 1.06l-4 4a.75.75 0 0 1-1.06 0l-4-4a.75.75 0 0 1 0-1.06Z"
                            fill="currentColor"
                          />
                        </svg>
                      </span>
                    </button>
                    <transition name="version-menu">
                      <ul v-if="isVersionMenuOpen" class="detail-meta__menu" role="listbox">
                        <li v-for="version in historyVersions" :key="version">
                          <button
                            class="detail-meta__menu-item"
                            :class="{ 'is-active': version === effectiveVersion }"
                            type="button"
                            @click="selectVersion(version)"
                          >
                            <span>{{ version }}</span>
                            <span v-if="version === effectiveVersion" class="detail-meta__menu-check" aria-hidden="true">
                              <svg viewBox="0 0 20 20" role="presentation">
                                <path
                                  d="M15.78 6.97a.75.75 0 0 1 0 1.06l-6 6a.75.75 0 0 1-1.06 0l-2.5-2.5a.75.75 0 0 1 1.06-1.06l1.97 1.97l5.47-5.47a.75.75 0 0 1 1.06 0Z"
                                  fill="currentColor"
                                />
                              </svg>
                            </span>
                          </button>
                        </li>
                      </ul>
                    </transition>
                  </div>
                </div>
                <small class="detail-meta__hint">切换后会展示对应版本的 Skill 详情内容。</small>
              </div>
              <div v-if="skill.contributor" class="detail-meta__item">
                <span>上传者</span>
                <code>{{ skill.contributor }}</code>
              </div>
              <CommandSnippet label="Skill 安装" :command="skill.install_command" compact />
              <div v-if="skill.source_repository || skill.detail_url" class="detail-meta__item">
                <span>来源信息</span>
                <code v-if="skill.source_repository">{{ skill.source_repository }}</code>
                <a v-if="skill.detail_url" :href="skill.detail_url" target="_blank" rel="noreferrer">
                  在 skills.sh 打开原始详情
                </a>
              </div>
            </div>

            <article class="markdown-body detail-modal__body" v-html="skill.description_html"></article>
          </template>
        </div>
      </div>
    </transition>
  </teleport>
</template>
