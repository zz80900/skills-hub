<script setup>
import { onBeforeUnmount, watch } from 'vue'

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
        <div class="detail-modal__dialog detail-modal__dialog--compact" :style="{ width }" role="dialog" aria-modal="true">
          <button class="detail-modal__close" type="button" aria-label="关闭弹层" @click="closeModal">
            关闭
          </button>

          <div class="detail-modal__header">
            <div>
              <h2>{{ title }}</h2>
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
