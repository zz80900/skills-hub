<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const remoteLoadingMore = ref(false)
const error = ref('')
const remoteError = ref('')
const search = ref('')
const localSkills = ref([])
const remoteSkills = ref([])
const cliInstallCommand = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const selectedSkill = ref(null)
const remotePage = ref(1)
const remotePageSize = ref(12)
const remoteHasMore = ref(false)
const remoteSentinel = ref(null)
const showBackToTop = ref(false)
let searchTimer = null
let detailRequestId = 0
let remoteObserver = null

const infoTabs = [
  { key: 'guide', label: '使用教程' },
  { key: 'cli', label: '安装 CLI' },
]
const libraryTabs = [
  { key: 'local', label: '本地库' },
  { key: 'skills_sh', label: 'skills.sh' },
]

const activeInfoTab = computed(() =>
  infoTabs.some((tab) => tab.key === route.query.panel) ? route.query.panel : '',
)
const activeLibraryTab = computed(() =>
  libraryTabs.some((tab) => tab.key === route.query.tab) ? route.query.tab : 'local',
)
const isSkillModalOpen = computed(() => Boolean(route.query.skill))
const isInfoModalOpen = computed(() => Boolean(activeInfoTab.value))
const infoModalTitle = computed(() => (activeInfoTab.value === 'cli' ? '安装 CLI' : '使用教程'))
const infoModalSummary = computed(() =>
  activeInfoTab.value === 'cli'
    ? '先安装 ssc-skills CLI，再通过首页复制具体 Skill 安装命令。'
    : '本地库和 skills.sh 通过 Tab 切换展示，skills.sh 支持瀑布流加载。',
)
const activeDetailSource = computed(() =>
  typeof route.query.source === 'string' && route.query.source ? route.query.source : 'local',
)
const localTabSummary = computed(() =>
  search.value ? `匹配 ${localSkills.value.length} 个结果` : `当前共 ${localSkills.value.length} 个 Skill`,
)
const remoteTabSummary = computed(() => {
  if (search.value) {
    return `已加载 ${remoteSkills.value.length} 个匹配结果`
  }
  return `已加载 ${remoteSkills.value.length} 个 skills.sh Skill`
})

function buildHomeQuery(overrides = {}) {
  const nextQuery = { ...route.query, ...overrides }
  Object.keys(nextQuery).forEach((key) => {
    if (nextQuery[key] === undefined || nextQuery[key] === null || nextQuery[key] === '') {
      delete nextQuery[key]
    }
  })
  return nextQuery
}

function mergeRemoteSkills(items) {
  const merged = [...remoteSkills.value]
  const seen = new Set(merged.map((skill) => `${skill.source}:${skill.slug}`))
  items.forEach((skill) => {
    const key = `${skill.source}:${skill.slug}`
    if (!seen.has(key)) {
      seen.add(key)
      merged.push(skill)
    }
  })
  remoteSkills.value = merged
}

async function loadSkills(keyword = '', options = {}) {
  const nextPage = options.page || 1
  const appendRemote = Boolean(options.appendRemote)

  if (appendRemote) {
    remoteLoadingMore.value = true
  } else {
    loading.value = true
    error.value = ''
    remoteError.value = ''
  }

  try {
    const payload = await fetchSkills(keyword, { page: nextPage, pageSize: remotePageSize.value })
    localSkills.value = payload.local_items || []
    cliInstallCommand.value = payload.cli_install_command
    remoteError.value = payload.remote_error || ''
    remotePage.value = payload.remote_page || nextPage
    remotePageSize.value = payload.remote_page_size || remotePageSize.value
    remoteHasMore.value = Boolean(payload.remote_has_more)

    if (appendRemote) {
      mergeRemoteSkills(payload.remote_items || [])
    } else {
      remoteSkills.value = payload.remote_items || []
    }
  } catch (err) {
    if (appendRemote) {
      remoteError.value = err.message
    } else {
      error.value = err.message
    }
  } finally {
    if (appendRemote) {
      remoteLoadingMore.value = false
    } else {
      loading.value = false
    }
  }
}

async function loadMoreRemoteSkills() {
  if (loading.value || remoteLoadingMore.value || !remoteHasMore.value || remoteError.value) {
    return
  }
  await loadSkills(search.value, { page: remotePage.value + 1, appendRemote: true })
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

function handleLibraryTabSelect(tabKey) {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ tab: tabKey }),
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

function handleWindowScroll() {
  showBackToTop.value = window.scrollY > 480
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetRemoteObserver() {
  if (remoteObserver) {
    remoteObserver.disconnect()
    remoteObserver = null
  }
}

async function syncRemoteObserver() {
  resetRemoteObserver()
  await nextTick()
  if (
    activeLibraryTab.value !== 'skills_sh'
    || !remoteSentinel.value
    || !remoteHasMore.value
    || remoteLoadingMore.value
    || loading.value
    || remoteError.value
  ) {
    return
  }

  remoteObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        loadMoreRemoteSkills()
      }
    },
    { rootMargin: '320px 0px' },
  )
  remoteObserver.observe(remoteSentinel.value)
}

watch(search, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    loadSkills(value, { page: 1 })
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

watch(
  [activeLibraryTab, remoteHasMore, remoteLoadingMore, loading, remoteError, () => remoteSkills.value.length],
  () => {
    syncRemoteObserver()
  },
)

onMounted(() => {
  loadSkills('', { page: 1 })
  handleWindowScroll()
  window.addEventListener('scroll', handleWindowScroll, { passive: true })
})

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer)
  resetRemoteObserver()
  window.removeEventListener('scroll', handleWindowScroll)
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
          <input
            id="skill-search"
            v-model.trim="search"
            class="text-input"
            type="search"
            placeholder="例如：plm、admin、markdown"
          />
        </label>
      </section>

      <section class="library-tabs" aria-label="Skill 来源切换">
        <button
          v-for="tab in libraryTabs"
          :key="tab.key"
          class="library-tabs__button"
          :class="{ 'is-active': activeLibraryTab === tab.key }"
          type="button"
          @click="handleLibraryTabSelect(tab.key)"
        >
          {{ tab.label }}
        </button>
      </section>

      <section v-if="error" class="feedback feedback--error">{{ error }}</section>
      <section v-else-if="loading" class="feedback">正在加载 Skills...</section>
      <template v-else>
        <section v-if="activeLibraryTab === 'local'" class="skill-section">
          <div class="skill-section__header">
            <div>
              <p class="eyebrow">本地库</p>
              <h2>内部 Skills</h2>
            </div>
            <p class="skill-section__summary">{{ localTabSummary }}</p>
          </div>
          <section v-if="!localSkills.length" class="feedback">
            {{ search ? `本地库没有找到与“${search}”匹配的 Skill。` : '本地库当前还没有 Skill。' }}
          </section>
          <section v-else class="skills-grid">
            <SkillCard
              v-for="skill in localSkills"
              :key="`${skill.source}:${skill.slug}`"
              :skill="skill"
              @select="openSkillDetail"
            />
          </section>
        </section>

        <section v-else class="skill-section">
          <div class="skill-section__header">
            <div>
              <p class="eyebrow">skills.sh</p>

            </div>
            <p class="skill-section__summary">{{ remoteTabSummary }}</p>
          </div>
          <section v-if="remoteError" class="feedback feedback--error">{{ remoteError }}</section>
          <section v-else-if="!remoteSkills.length" class="feedback">
            {{ search ? `skills.sh 没有找到与“${search}”匹配的 Skill。` : '当前未获取到 skills.sh Skill。' }}
          </section>
          <section v-else class="skills-grid skills-grid--masonry">
            <SkillCard
              v-for="skill in remoteSkills"
              :key="`${skill.source}:${skill.slug}`"
              :skill="skill"
              @select="openSkillDetail"
            />
          </section>
          <div
            v-if="remoteSkills.length && (remoteHasMore || remoteLoadingMore)"
            ref="remoteSentinel"
            class="skills-waterfall-status"
          >
            {{ remoteLoadingMore ? '正在继续加载 skills.sh Skills...' : '向下滚动继续加载' }}
          </div>
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
        <li>通过上方 Tab 在本地库与 skills.sh 之间切换。</li>
        <li>切到 skills.sh 后向下滚动，可按瀑布流方式持续加载更多 Skill。</li>
      </ol>
      <CommandSnippet
        v-else-if="activeInfoTab === 'cli'"
        label="CLI 安装命令"
        :command="cliInstallCommand"
        compact
      />
    </InfoModal>
    <transition name="back-to-top-fade">
      <button
        v-if="showBackToTop"
        class="back-to-top"
        type="button"
        aria-label="返回顶部"
        @click="scrollToTop"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 5.5a.75.75 0 0 1 .53.22l5.25 5.25a.75.75 0 1 1-1.06 1.06l-3.97-3.97V18a.75.75 0 0 1-1.5 0V8.06l-3.97 3.97a.75.75 0 0 1-1.06-1.06l5.25-5.25A.75.75 0 0 1 12 5.5Z"
            fill="currentColor"
          />
        </svg>
      </button>
    </transition>
  </div>
</template>
