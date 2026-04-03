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
const remoteError = ref('')
const search = ref('')
const localSkills = ref([])
const remoteSkills = ref([])
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
  activeInfoTab.value === 'cli'
    ? '先安装 ssc-skills CLI，再通过首页复制具体 Skill 安装命令。'
    : '一个搜索框同时检索本地库和 skills.sh，详情在当前页弹窗查看。',
)
const activeDetailSource = computed(() =>
  typeof route.query.source === 'string' && route.query.source ? route.query.source : 'local',
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
  remoteError.value = ''
  try {
    const payload = await fetchSkills(keyword)
    localSkills.value = payload.local_items || []
    remoteSkills.value = payload.remote_items || []
    cliInstallCommand.value = payload.cli_install_command
    remoteError.value = payload.remote_error || ''
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadSkillDetail(source, slug) {
  const requestId = detailRequestId + 1
  detailRequestId = requestId
  detailLoading.value = true
  detailError.value = ''
  try {
    const payload = await fetchSkill(source, slug)
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

function openSkillDetail(skill) {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: skill.slug, source: skill.source }),
  })
}

function closeSkillDetail() {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: null, source: null }),
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
  [() => route.query.skill, () => route.query.source],
  ([slug, source]) => {
    if (typeof slug === 'string' && slug) {
      loadSkillDetail(typeof source === 'string' && source ? source : 'local', slug)
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
            搜索 Skill，统一检索本地库与 skills.sh。
          </span>
          <span class="search-field__hint">
            {{ search ? `当前关键词：${search}` : '输入后自动筛选两套来源' }}
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
      <template v-else>
        <section class="skill-section">
          <div class="skill-section__header">
            <div>
              <p class="eyebrow">本地库</p>
              <h2>内部 Skills</h2>
            </div>
            <p class="skill-section__summary">
              {{ search ? `匹配 ${localSkills.length} 个结果` : `当前共 ${localSkills.length} 个 Skill` }}
            </p>
          </div>
          <section v-if="!localSkills.length" class="feedback">
            {{ search ? `本地库没有找到与“${search}”匹配的 Skill。` : '本地库当前还没有 Skill。' }}
          </section>
          <section v-else class="skills-grid">
            <SkillCard v-for="skill in localSkills" :key="`${skill.source}:${skill.slug}`" :skill="skill" @select="openSkillDetail" />
          </section>
        </section>

        <section class="skill-section">
          <div class="skill-section__header">
            <div>
              <p class="eyebrow">skills.sh</p>
              <h2>官方 Agent Skills</h2>
            </div>
            <p class="skill-section__summary">
              {{ search ? `匹配 ${remoteSkills.length} 个结果` : `当前展示 ${remoteSkills.length} 个热门 Skill` }}
            </p>
          </div>
          <section v-if="remoteError" class="feedback feedback--error">{{ remoteError }}</section>
          <section v-else-if="!remoteSkills.length" class="feedback">
            {{ search ? `skills.sh 没有找到与“${search}”匹配的 Skill。` : '当前未获取到 skills.sh Skill。' }}
          </section>
          <section v-else class="skills-grid">
            <SkillCard
              v-for="skill in remoteSkills"
              :key="`${skill.source}:${skill.slug}`"
              :skill="skill"
              @select="openSkillDetail"
            />
          </section>
        </section>
      </template>
    </main>
    <SkillDetailModal
      :open="isSkillModalOpen"
      :loading="detailLoading"
      :error="detailError"
      :skill="selectedSkill"
      :source="activeDetailSource"
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
        <li>先点击“安装 CLI”，复制并执行 ssc-skills CLI 安装命令。</li>
        <li>回到主页，通过搜索框统一检索本地库和 skills.sh。</li>
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
