<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CommandSnippet from '../../components/CommandSnippet.vue'
import InfoModal from '../../components/InfoModal.vue'
import SiteHeader from '../../components/SiteHeader.vue'
import SkillCard from '../../components/SkillCard.vue'
import SkillDetailModal from '../../components/SkillDetailModal.vue'
import { fetchSkill, fetchSkills } from '../../services/api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const search = ref('')
const skills = ref([])
const cliInstallCommand = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const selectedSkill = ref(null)
let searchTimer = null
let detailRequestId = 0
const infoTabs = [
  { key: 'guide', label: '使用教程' },
  { key: 'cli', label: '安装 CLI' },
]

const activeInfoTab = computed(() =>
  infoTabs.some((tab) => tab.key === route.query.panel) ? route.query.panel : '',
)
const isSkillModalOpen = computed(() => Boolean(route.query.skill))
const isInfoModalOpen = computed(() => Boolean(activeInfoTab.value))
const infoModalTitle = computed(() => (activeInfoTab.value === 'cli' ? '安装 CLI' : '使用教程'))
const infoModalSummary = computed(() =>
  activeInfoTab.value === 'cli' ? 'CLI 安装仅在这里集中展示，避免占用主页面空间。' : '按最少步骤完成安装、搜索和查看详情。',
)

function buildHomeQuery(overrides = {}) {
  const nextQuery = { ...route.query, ...overrides }
  Object.keys(nextQuery).forEach((key) => {
    if (nextQuery[key] === undefined || nextQuery[key] === null || nextQuery[key] === '') {
      delete nextQuery[key]
    }
  })
  return nextQuery
}

async function loadSkills(keyword = '') {
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchSkills(keyword)
    skills.value = payload.items
    cliInstallCommand.value = payload.cli_install_command
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadSkillDetail(name) {
  const requestId = detailRequestId + 1
  detailRequestId = requestId
  detailLoading.value = true
  detailError.value = ''
  try {
    const payload = await fetchSkill(name)
    if (detailRequestId !== requestId) {
      return
    }
    selectedSkill.value = payload
  } catch (err) {
    if (detailRequestId !== requestId) {
      return
    }
    detailError.value = err.message
    selectedSkill.value = null
  } finally {
    if (detailRequestId === requestId) {
      detailLoading.value = false
    }
  }
}

function handleInfoTabSelect(tabKey) {
  const nextTab = activeInfoTab.value === tabKey ? null : tabKey
  router.replace({
    name: 'home',
    query: buildHomeQuery({ panel: nextTab }),
  })
}

function openSkillDetail(name) {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: name }),
  })
}

function closeSkillDetail() {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: null }),
  })
}

function closeInfoModal() {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ panel: null }),
  })
}

watch(search, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    loadSkills(value)
  }, 250)
})

watch(
  () => route.query.skill,
  (name) => {
    if (typeof name === 'string' && name) {
      loadSkillDetail(name)
      return
    }
    detailRequestId += 1
    detailLoading.value = false
    detailError.value = ''
    selectedSkill.value = null
  },
  { immediate: true },
)

onMounted(() => {
  loadSkills()
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="page-shell">
    <SiteHeader :tabs="infoTabs" :active-tab="activeInfoTab" @tab-select="handleInfoTabSelect" />
    <main class="page-content">
      <section class="search-panel search-panel--home">
        <label class="search-field search-field--inline" for="skill-search">
          <span class="search-field__label search-field__label--inline">
            搜索 Skill，支持名称、用途和关键描述词。
          </span>
          <span class="search-field__hint">
            {{ search ? `当前关键词：${search}` : '输入后自动筛选' }}
          </span>
          <input
            id="skill-search"
            v-model.trim="search"
            class="text-input"
            type="search"
            placeholder="例如：plm、admin、markdown"
          />
        </label>
      </section>
      <section v-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="loading" class="feedback">正在加载 Skills...</section>
      <section v-else-if="!skills.length" class="feedback">没有匹配的 Skill。</section>

      <section v-else class="skills-grid">
        <SkillCard v-for="skill in skills" :key="skill.name" :skill="skill" @select="openSkillDetail" />
      </section>
    </main>
    <SkillDetailModal
      :open="isSkillModalOpen"
      :loading="detailLoading"
      :error="detailError"
      :skill="selectedSkill"
      @close="closeSkillDetail"
    />
    <InfoModal
      :open="isInfoModalOpen"
      :title="infoModalTitle"
      :summary="infoModalSummary"
      width="720px"
      @close="closeInfoModal"
    >
      <ol v-if="activeInfoTab === 'guide'" class="info-modal__list">
        <li>先在顶部点击“安装 CLI”，复制并执行 CLI 安装命令。</li>
        <li>回到主页列表，通过搜索框按名称或用途筛选 Skill。</li>
        <li>点击任意 Skill 卡片，在当前页弹出层中查看说明与安装命令。</li>
      </ol>
      <CommandSnippet
        v-else-if="activeInfoTab === 'cli'"
        label="CLI 安装命令"
        :command="cliInstallCommand"
        compact
      />
    </InfoModal>
  </div>
</template>
