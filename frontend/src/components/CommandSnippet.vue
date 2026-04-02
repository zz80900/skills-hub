<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  label: {
    type: String,
    required: true,
  },
  command: {
    type: String,
    required: true,
  },
  compact: {
    type: Boolean,
    default: false,
  },
})

const copied = ref(false)
let resetTimer = null

const statusText = computed(() => (copied.value ? '已复制' : '点击复制'))

function resetCopiedState() {
  window.clearTimeout(resetTimer)
  resetTimer = window.setTimeout(() => {
    copied.value = false
  }, 1800)
}

function fallbackCopy(text) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

async function copyCommand() {
  if (!props.command) {
    return
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.command)
    } else {
      fallbackCopy(props.command)
    }
    copied.value = true
    resetCopiedState()
  } catch (error) {
    copied.value = false
  }
}

onBeforeUnmount(() => {
  window.clearTimeout(resetTimer)
})
</script>

<template>
  <button
    type="button"
    class="command-snippet"
    :class="{ 'command-snippet--compact': compact, 'command-snippet--copied': copied }"
    :aria-label="`${label}，点击复制命令`"
    @click="copyCommand"
  >
    <span class="command-snippet__meta">
      <span class="command-snippet__label">{{ label }}</span>
      <span class="command-snippet__status">{{ statusText }}</span>
    </span>
    <code class="command-snippet__code">{{ command }}</code>
  </button>
</template>
