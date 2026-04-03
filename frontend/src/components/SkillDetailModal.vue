<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'

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

function closeModal() {
  emit('close')
}

function handleBackdropClick(event) {
  if (event.target === event.currentTarget) {
    closeModal()
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    closeModal()
  }
}

function handleVersionChange(event) {
  emit('version-select', event.target.value)
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      window.addEventListener('keydown', handleKeydown)
      document.body.style.overflow = 'hidden'
      return
    }
    window.removeEventListener('keydown', handleKeydown)
    document.body.style.overflow = ''
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
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
                <select class="text-input detail-meta__select" :value="effectiveVersion" @change="handleVersionChange">
                  <option v-for="version in historyVersions" :key="version" :value="version">
                    {{ version }}
                  </option>
                </select>
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
