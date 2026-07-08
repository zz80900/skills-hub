<script setup>
import { computed } from 'vue'

import CommandSnippet from './CommandSnippet.vue'
import { useModalLifecycle } from '../composables/useModalLifecycle'

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
})

const emit = defineEmits(['close'])

const titleId = computed(() => `skill-detail-title-${props.skill?.slug || props.skill?.name || 'loading'}`)
const sourceName = computed(() =>
  props.skill?.source_label || (props.source === 'skills_sh' ? 'skills.sh' : '本地库'),
)

function closeModal() {
  emit('close')
}

const { dialogRef, handleBackdropClick } = useModalLifecycle(() => props.open, closeModal)
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div v-if="open" class="detail-drawer" @click="handleBackdropClick">
        <aside
          ref="dialogRef"
          class="detail-drawer__panel"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
        >
          <header class="detail-drawer__top">
            <div class="detail-drawer__titlebar">
              <div class="detail-drawer__identity">
                <h2 :id="titleId">{{ skill?.name || 'Skill 详情' }}</h2>
                <span class="detail-drawer__summary">{{ sourceName }}</span>
              </div>
              <button class="detail-drawer__close" type="button" aria-label="关闭详情" @click="closeModal">
                关闭
              </button>
            </div>
            <div
              v-if="skill && !loading && !error"
              class="detail-drawer__toolbar"
              aria-label="Skill 关键信息与操作"
            >
              <dl v-if="source === 'local' || skill.contributor || skill.source_repository" class="detail-facts">
                <div v-if="source === 'local'" class="detail-fact">
                  <dt>版本</dt>
                  <dd><code>{{ skill.version || '未设置' }}</code></dd>
                </div>
                <div v-if="skill.contributor" class="detail-fact">
                  <dt>上传者</dt>
                  <dd><code>{{ skill.contributor }}</code></dd>
                </div>
                <div v-if="skill.source_repository" class="detail-fact">
                  <dt>来源</dt>
                  <dd><code>{{ skill.source_repository }}</code></dd>
                </div>
              </dl>
              <CommandSnippet label="安装命令" :command="skill.install_command" compact />
              <a
                v-if="skill.detail_url"
                class="detail-source-link"
                :href="skill.detail_url"
                target="_blank"
                rel="noreferrer"
              >
                打开原始详情
              </a>
            </div>
          </header>

          <section v-if="loading" class="feedback detail-drawer__feedback">正在加载 Skill 详情...</section>
          <section v-else-if="error" class="feedback feedback--error detail-drawer__feedback">{{ error }}</section>
          <template v-else-if="skill">
            <article class="markdown-body detail-drawer__body" v-html="skill.description_html"></article>
          </template>
        </aside>
      </div>
    </transition>
  </teleport>
</template>
