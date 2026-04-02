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
  <button type="button" class="skill-card skill-card--button" @click="emit('select', skill.name)">
    <div class="skill-card__top">
      <div>
        <span class="skill-card__eyebrow">Skill</span>
        <h3>{{ skill.name }}</h3>
      </div>
      <span class="skill-card__badge">查看详情</span>
    </div>
    <div class="skill-card__description" v-html="skill.description_html"></div>
    <span class="skill-card__hint">点击条目后以模态框查看描述与安装命令</span>
  </button>
</template>
