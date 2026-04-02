<script setup>
defineProps({
  tabs: {
    type: Array,
    default: () => [],
  },
  activeTab: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['tab-select'])

function handleTabClick(tabKey) {
  emit('tab-select', tabKey)
}
</script>

<template>
  <header class="site-header">
    <div class="site-header__inner">
      <router-link class="site-header__brand" to="/">SSC Skills Library</router-link>
      <nav class="site-header__nav">
        <router-link class="site-header__link" to="/">Skills</router-link>
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="site-header__link site-header__link--button"
          :class="{ 'is-active': activeTab === tab.key }"
          type="button"
          @click="handleTabClick(tab.key)"
        >
          {{ tab.label }}
        </button>
        <router-link class="site-header__link" to="/admin">管理后台</router-link>
      </nav>
    </div>
  </header>
</template>
