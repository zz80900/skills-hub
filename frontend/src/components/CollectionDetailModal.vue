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
  collection: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close'])

const titleId = computed(() => `collection-detail-title-${props.collection?.slug || 'loading'}`)
const sourceName = computed(() => props.collection?.source_label || 'Skill 集合')
const previewItems = computed(() => props.collection?.preview_items || [])
const itemCountLabel = computed(() => `${Number(props.collection?.item_count) || 0} 个 Skill`)

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
                <h2 :id="titleId">{{ collection?.name || 'Skill 集合详情' }}</h2>
                <span class="detail-drawer__summary">
                  {{ collection?.slug ? `${sourceName} · ${collection.slug}` : sourceName }}
                </span>
              </div>
              <button class="detail-drawer__close" type="button" aria-label="关闭详情" @click="closeModal">
                关闭
              </button>
            </div>
            <div
              v-if="collection && !loading && !error"
              class="detail-drawer__toolbar"
              aria-label="Skill 集合关键信息与操作"
            >
              <dl class="detail-facts">
                <div class="detail-fact">
                  <dt>版本</dt>
                  <dd><code>{{ collection.version || '未设置' }}</code></dd>
                </div>
                <div class="detail-fact">
                  <dt>范围</dt>
                  <dd><code>{{ collection.scope_label || '公开' }}</code></dd>
                </div>
                <div class="detail-fact">
                  <dt>条目</dt>
                  <dd><code>{{ itemCountLabel }}</code></dd>
                </div>
              </dl>
              <CommandSnippet label="Skill 集合安装" :command="collection.install_command" compact />
            </div>
          </header>

          <section v-if="loading" class="feedback detail-drawer__feedback">正在加载 Skill 集合详情...</section>
          <section v-else-if="error" class="feedback feedback--error detail-drawer__feedback">{{ error }}</section>
          <template v-else-if="collection">
            <section v-if="previewItems.length" class="detail-drawer__body">
              <ul class="collection-items-list">
                <li v-for="item in previewItems" :key="item.path">
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.path }}</span>
                  <code>{{ item.file_count || 0 }} 个文件</code>
                </li>
              </ul>
            </section>
            <article class="markdown-body detail-drawer__body" v-html="collection.description_html"></article>
          </template>
        </aside>
      </div>
    </transition>
  </teleport>
</template>
