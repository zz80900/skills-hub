<script setup>
const props = defineProps({
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
  empty: {
    type: Boolean,
    default: false,
  },
  loadingText: {
    type: String,
    default: '正在加载...',
  },
  emptyText: {
    type: String,
    default: '当前没有数据。',
  },
  retryLabel: {
    type: String,
    default: '重试',
  },
  showRetry: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['retry'])
</script>

<template>
  <section v-if="error" class="feedback feedback--error list-state">
    <span>{{ error }}</span>
    <button v-if="showRetry" class="button button--ghost" type="button" @click="emit('retry')">
      {{ retryLabel }}
    </button>
  </section>
  <section v-else-if="loading" class="feedback list-state">
    {{ loadingText }}
  </section>
  <section v-else-if="empty" class="feedback list-state">
    <slot name="empty">{{ emptyText }}</slot>
  </section>
  <slot v-else />
</template>
