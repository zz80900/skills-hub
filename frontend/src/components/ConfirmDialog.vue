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
  confirmLabel: {
    type: String,
    default: '确认',
  },
  cancelLabel: {
    type: String,
    default: '取消',
  },
  tone: {
    type: String,
    default: 'danger',
  },
  busy: {
    type: Boolean,
    default: false,
  },
  width: {
    type: String,
    default: '560px',
  },
  variant: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['close', 'confirm'])

const titleId = computed(() => `confirm-dialog-title-${props.title.replace(/\s+/g, '-').toLowerCase()}`)

function closeDialog() {
  if (props.busy) {
    return
  }
  emit('close')
}

function confirmAction() {
  if (props.busy) {
    return
  }
  emit('confirm')
}

function handleDialogBackdropClick(event) {
  if (props.busy) {
    return
  }
  handleBackdropClick(event)
}

const { dialogRef, handleBackdropClick } = useModalLifecycle(() => props.open, closeDialog)
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div v-if="open" class="detail-modal" @click="handleDialogBackdropClick">
        <div
          ref="dialogRef"
          :class="[
            'detail-modal__dialog detail-modal__dialog--compact confirm-dialog',
            variant ? `confirm-dialog--${variant}` : '',
            variant === 'api-key' ? 'api-key-modal' : '',
          ]"
          :style="{ width }"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
        >
          <button class="detail-modal__close" type="button" aria-label="关闭弹层" :disabled="busy" @click="closeDialog">
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

          <div class="confirm-dialog__actions">
            <button class="button button--ghost" type="button" :disabled="busy" @click="closeDialog">
              {{ cancelLabel }}
            </button>
            <button class="button" :class="`button--${tone}`" type="button" :disabled="busy" @click="confirmAction">
              {{ busy ? '处理中...' : confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>
