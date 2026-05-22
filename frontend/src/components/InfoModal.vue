<script setup>
import { computed } from 'vue'

import { useModalLifecycle } from '../composables/useModalLifecycle'

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    required: true,
  },
  summary: {
    type: String,
    default: '',
  },
  width: {
    type: String,
    default: '760px',
  },
})

const emit = defineEmits(['close'])

const titleId = computed(() => `info-modal-title-${props.title.replace(/\s+/g, '-').toLowerCase()}`)

function closeModal() {
  emit('close')
}

const { dialogRef, handleBackdropClick } = useModalLifecycle(() => props.open, closeModal)
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div v-if="open" class="detail-modal" @click="handleBackdropClick">
        <div
          ref="dialogRef"
          class="detail-modal__dialog detail-modal__dialog--compact"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
        >
          <button class="detail-modal__close" type="button" aria-label="关闭弹层" @click="closeModal">
            关闭
          </button>

          <div class="detail-modal__header">
            <div>
              <h2 :id="titleId">{{ title }}</h2>
            </div>
            <p v-if="summary" class="detail-modal__summary">{{ summary }}</p>
          </div>

          <div class="detail-modal__body detail-modal__body--plain">
            <slot />
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>
