<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import CommandSnippet from '../../components/CommandSnippet.vue'
import SiteHeader from '../../components/SiteHeader.vue'
import { fetchSkill } from '../../services/api'

const route = useRoute()
const loading = ref(false)
const error = ref('')
const skill = ref(null)

async function loadSkill(name) {
  loading.value = true
  error.value = ''
  try {
    skill.value = await fetchSkill(name)
  } catch (err) {
    error.value = err.message
    skill.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.name,
  (name) => {
    if (name) {
      loadSkill(name)
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="page-shell">
    <SiteHeader />
    <main class="page-content page-content--narrow">
      <section v-if="loading" class="feedback">正在加载 Skill 详情...</section>
      <section v-else-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="skill" class="detail-panel">
        <div class="detail-panel__header">
          <p class="eyebrow">Skill 详情</p>
          <h1>{{ skill.name }}</h1>
        </div>

        <div class="detail-meta">
          <CommandSnippet label="CLI 安装" :command="skill.cli_install_command" />
          <CommandSnippet label="Skill 安装" :command="skill.install_command" />
          <div class="detail-meta__item">
            <span>ZIP 下载</span>
            <a :href="skill.package_url" target="_blank" rel="noreferrer">{{ skill.package_url }}</a>
          </div>
        </div>

        <article class="markdown-body" v-html="skill.description_html"></article>
      </section>
    </main>
  </div>
</template>
