<script setup>
defineProps({
  skill: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['select'])
</script>

<template>
  <button type="button" class="skill-card skill-card--button" @click="emit('select', skill)">
    <div class="skill-card__top">
      <div class="skill-card__title">
        <h3>{{ skill.name }}</h3>
        <span class="skill-card__meta">{{ skill.source_label }}</span>
      </div>
      <span class="skill-card__badge">
        {{ skill.installs ? `${skill.installs} installs` : '查看详情' }}
      </span>
    </div>
    <div class="skill-card__description" v-html="skill.description_html"></div>
    <span class="skill-card__hint">点击查看描述与安装命令</span>
  </button>
</template>
