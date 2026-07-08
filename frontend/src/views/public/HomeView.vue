<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SiteHeader from '../../components/SiteHeader.vue'
import SkillCard from '../../components/SkillCard.vue'
import SkillDetailModal from '../../components/SkillDetailModal.vue'
import ListState from '../../components/ListState.vue'
import { fetchLocalSkills, fetchRemoteSkills, fetchSkill } from '../../services/api'

const route = useRoute()
const router = useRouter()
const localLoading = ref(false)
const remoteLoading = ref(false)
const remoteLoadingMore = ref(false)
const error = ref('')
const remoteError = ref('')
const search = ref('')
const localSkills = ref([])
const remoteSkills = ref([])
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
let localRequestId = 0
let remoteRequestId = 0
let remoteObserver = null

const libraryTabs = [
  { key: 'local', label: '本地库' },
  { key: 'skills_sh', label: 'skills.sh' },
]

const activeLibraryTab = computed(() =>
  libraryTabs.some((tab) => tab.key === route.query.tab) ? route.query.tab : 'local',
)
const isSkillModalOpen = computed(() => Boolean(route.query.skill))
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
const activeLibraryLabel = computed(() =>
  libraryTabs.find((tab) => tab.key === activeLibraryTab.value)?.label || '本地库',
)
const activeSkills = computed(() => (activeLibraryTab.value === 'local' ? localSkills.value : remoteSkills.value))
const activeSummary = computed(() => (activeLibraryTab.value === 'local' ? localTabSummary.value : remoteTabSummary.value))
const activeLoading = computed(() => (activeLibraryTab.value === 'local' ? localLoading.value : remoteLoading.value))
const activeLoadingText = computed(() => (activeLibraryTab.value === 'local' ? '正在加载本地库...' : '正在加载 skills.sh...'))
const activeError = computed(() => (activeLibraryTab.value === 'local' ? error.value : remoteError.value))
const activeEmptyText = computed(() => {
  if (activeLibraryTab.value === 'local') {
    return search.value ? `本地库没有找到与“${search.value}”匹配的 Skill。` : '本地库当前还没有 Skill。'
  }
  return search.value ? `skills.sh 没有找到与“${search.value}”匹配的 Skill。` : '当前未获取到 skills.sh Skill。'
})
const sourcePanels = computed(() => [
  {
    key: 'local',
    label: '本地库',
    title: '内部资产',
    count: localSkills.value.length,
    summary: localLoading.value ? '正在加载本地库' : error.value ? '加载失败' : localTabSummary.value,
    loading: localLoading.value,
    error: error.value,
  },
  {
    key: 'skills_sh',
    label: 'skills.sh',
    title: '外部发现',
    count: remoteSkills.value.length,
    summary: remoteLoading.value ? '正在加载 skills.sh' : remoteError.value ? '加载失败' : remoteTabSummary.value,
    loading: remoteLoading.value,
    error: remoteError.value,
  },
])

function buildHomeQuery(overrides = {}) {
  const nextQuery = { ...route.query, ...overrides }
  delete nextQuery.panel
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

async function loadLocalSkills(keyword = '') {
  const requestId = localRequestId + 1
  localRequestId = requestId
  localLoading.value = true
  error.value = ''

  try {
    const payload = await fetchLocalSkills(keyword)
    if (requestId !== localRequestId) {
      return
    }
    localSkills.value = payload.items || []
  } catch (err) {
    if (requestId !== localRequestId) {
      return
    }
    error.value = err.message
  } finally {
    if (requestId === localRequestId) {
      localLoading.value = false
    }
  }
}

async function loadRemoteSkills(keyword = '', options = {}) {
  const nextPage = options.page || 1
  const appendRemote = Boolean(options.appendRemote)
  const requestId = appendRemote ? remoteRequestId : remoteRequestId + 1

  if (appendRemote) {
    remoteLoadingMore.value = true
  } else {
    remoteRequestId = requestId
    remoteLoading.value = true
    remoteError.value = ''
  }

  try {
    const payload = await fetchRemoteSkills(keyword, {
      page: nextPage,
      pageSize: remotePageSize.value,
    })
    if (requestId !== remoteRequestId) {
      return
    }

    remoteError.value = payload.error || ''
    remotePage.value = payload.page || nextPage
    remotePageSize.value = payload.page_size || remotePageSize.value
    remoteHasMore.value = Boolean(payload.has_more)

    if (appendRemote) {
      mergeRemoteSkills(payload.items || [])
    } else {
      remoteSkills.value = payload.items || []
    }
  } catch (err) {
    if (requestId !== remoteRequestId) {
      return
    }
    remoteError.value = err.message
  } finally {
    if (appendRemote) {
      remoteLoadingMore.value = false
    } else if (requestId === remoteRequestId) {
      remoteLoading.value = false
    }
  }
}

function refreshSkillLists(keyword = '') {
  loadLocalSkills(keyword)
  loadRemoteSkills(keyword, { page: 1 })
}

async function loadMoreRemoteSkills() {
  if (remoteLoading.value || remoteLoadingMore.value || !remoteHasMore.value || remoteError.value) {
    return
  }
  await loadRemoteSkills(search.value, { page: remotePage.value + 1, appendRemote: true })
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

function handleLibraryTabSelect(tabKey) {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ tab: tabKey }),
  })
}

function clearSearch() {
  if (!search.value) {
    return
  }
  search.value = ''
}

function retryLoadSkills() {
  if (activeLibraryTab.value === 'skills_sh') {
    loadRemoteSkills(search.value, { page: 1 })
    return
  }
  loadLocalSkills(search.value)
}

function openSkillDetail(skill) {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: skill.slug, source: skill.source, version: null }),
  })
}

function closeSkillDetail() {
  router.replace({
    name: 'home',
    query: buildHomeQuery({ skill: null, source: null, version: null }),
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
    || remoteLoading.value
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
    refreshSkillLists(value)
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
  [activeLibraryTab, remoteHasMore, remoteLoadingMore, remoteLoading, remoteError, () => remoteSkills.value.length],
  () => {
    syncRemoteObserver()
  },
)

onMounted(() => {
  refreshSkillLists('')
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
    <SiteHeader />
    <main class="page-content page-content--library">
      <section class="library-console">
        <div class="library-console__intro">
          <h1 class="library-title">Skill 目录</h1>
          <div class="library-console__meta" aria-label="Skill 来源状态">
            <span>{{ localTabSummary }}</span>
            <span>{{ remoteTabSummary }}</span>
          </div>
        </div>

        <div class="source-card-list" role="tablist" aria-label="Skill 来源切换">
          <button
            v-for="panel in sourcePanels"
            :key="panel.key"
            class="source-card"
            :class="{
              'is-active': activeLibraryTab === panel.key,
              'is-loading': panel.loading,
              'has-error': panel.error,
            }"
            type="button"
            role="tab"
            :aria-selected="activeLibraryTab === panel.key"
            :aria-busy="panel.loading ? 'true' : 'false'"
            @click="handleLibraryTabSelect(panel.key)"
          >
            <span class="source-card__label">{{ panel.label }}</span>
            <strong>{{ panel.title }}</strong>
            <span class="source-card__count">{{ panel.count }}</span>
            <span class="source-card__summary">{{ panel.summary }}</span>
          </button>
        </div>

        <label class="search-field search-field--home-control library-console__search" for="skill-search">
          <div class="search-field__meta">
            <span class="search-field__label">当前来源：{{ activeLibraryLabel }}</span>
            <span class="search-field__status">{{ activeSummary }}</span>
          </div>
          <div class="search-field__control">
            <span class="search-field__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" focusable="false">
                <path
                  d="m20.03 18.97-4.36-4.36a6.84 6.84 0 1 0-1.06 1.06l4.36 4.36a.75.75 0 0 0 1.06-1.06ZM5.5 10.25a4.75 4.75 0 1 1 9.5 0 4.75 4.75 0 0 1-9.5 0Z"
                  fill="currentColor"
                />
              </svg>
            </span>
            <input
              id="skill-search"
              v-model.trim="search"
              class="text-input"
              type="search"
              placeholder="搜索 Skill、作者或用途"
            />
            <button
              v-if="search"
              class="search-field__clear"
              type="button"
              @click="clearSearch"
            >
              清空
            </button>
          </div>
        </label>
      </section>

      <section class="library-results">
        <header class="library-results__bar" aria-live="polite">
          <span class="library-results__source">
            <span class="library-results__source-dot" aria-hidden="true"></span>
            {{ activeLibraryLabel }}
          </span>
          <p class="library-results__summary">{{ activeLoading ? activeLoadingText : activeSummary }}</p>
        </header>

        <ListState
          :error="activeError"
          :loading="activeLoading && !activeSkills.length"
          :empty="!activeSkills.length"
          :empty-text="activeEmptyText"
          :loading-text="activeLoadingText"
          @retry="retryLoadSkills"
        >
          <section
            class="skills-grid skills-grid--directory"
            :class="{ 'is-refreshing': activeLoading && activeSkills.length }"
          >
            <SkillCard
              v-for="skill in activeSkills"
              :key="`${skill.source}:${skill.slug}`"
              :skill="skill"
              @select="openSkillDetail"
            />
          </section>

          <div
            v-if="activeLibraryTab === 'skills_sh' && activeSkills.length && !remoteLoading && (remoteHasMore || remoteLoadingMore)"
            ref="remoteSentinel"
            class="skills-waterfall-status"
          >
            {{ remoteLoadingMore ? '正在继续加载 skills.sh Skills...' : '向下滚动继续加载' }}
          </div>
        </ListState>
      </section>
    </main>
    <SkillDetailModal
      :open="isSkillModalOpen"
      :loading="detailLoading"
      :error="detailError"
      :skill="selectedSkill"
      :source="activeDetailSource"
      @close="closeSkillDetail"
    />
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
