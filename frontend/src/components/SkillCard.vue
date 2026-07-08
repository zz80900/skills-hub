<script setup>
import { computed } from 'vue'

const props = defineProps({
  skill: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['select'])

const sourceLabel = computed(() =>
  props.skill.source_label || (props.skill.source === 'skills_sh' ? 'skills.sh' : '本地库'),
)
const detailMetric = computed(() => {
  if (Number.isFinite(props.skill.installs)) {
    return `安装 ${props.skill.installs}`
  }
  return ''
})
</script>

<template>
  <button type="button" class="skill-card skill-card--button" @click="emit('select', skill)">
    <span class="skill-card__rail" aria-hidden="true"></span>
    <div class="skill-card__content">
      <div class="skill-card__meta-row">
        <span class="skill-card__meta">{{ sourceLabel }}</span>
        <span v-if="skill.version" class="skill-card__version">{{ skill.version }}</span>
        <span v-if="detailMetric" class="skill-card__badge">{{ detailMetric }}</span>
      </div>
      <span class="skill-card__name-text">{{ skill.name }}</span>
      <div class="skill-card__description" v-html="skill.description_html"></div>
    </div>
    <span class="skill-card__action">打开</span>
  </button>
</template>
