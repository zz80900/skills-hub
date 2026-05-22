<script setup>
import { onMounted } from 'vue'

import { consumeStashedNotice, notices, pushNotice, dismissNotice } from '../services/feedback'

function hydrateNoticeQueue() {
  const pending = consumeStashedNotice()
  if (pending) {
    pushNotice(pending)
  }
}

onMounted(() => {
  hydrateNoticeQueue()
})
</script>

<template>
  <teleport to="body">
    <div class="notice-stack" aria-live="polite" aria-atomic="true">
      <transition-group name="notice-fade" tag="div" class="notice-stack__list">
        <article v-for="notice in notices" :key="notice.id" class="notice" :class="`notice--${notice.tone}`">
          <div class="notice__text">
            <strong v-if="notice.title">{{ notice.title }}</strong>
            <p>{{ notice.message }}</p>
          </div>
          <button class="notice__close" type="button" aria-label="关闭提示" @click="dismissNotice(notice.id)">
            ×
          </button>
        </article>
      </transition-group>
    </div>
  </teleport>
</template>
