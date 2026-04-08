import { reactive } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'ssc-skills-session-token'
const USER_KEY = 'ssc-skills-session-user'

function readToken() {
  return window.localStorage.getItem(TOKEN_KEY)
}

function readUser() {
  const raw = window.localStorage.getItem(USER_KEY)
  if (!raw) {
    return null
  }
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') {
      return null
    }
    if (typeof parsed.id !== 'number' || typeof parsed.username !== 'string' || typeof parsed.role !== 'string') {
      return null
    }
    return {
      ...parsed,
      source: typeof parsed.source === 'string' ? parsed.source : 'LOCAL',
      display_name: typeof parsed.display_name === 'string' && parsed.display_name.trim() ? parsed.display_name : null,
    }
  } catch {
    return null
  }
}

export const authState = reactive({
  token: readToken(),
  user: readUser(),
})

let publicConfigCache = null
let publicConfigRequest = null

if (authState.token && !authState.user) {
  window.localStorage.removeItem(TOKEN_KEY)
  authState.token = null
}

function buildUrl(path, params) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value)
      }
    })
  }
  return API_BASE ? url.toString() : `${path}${url.search}`
}

function normalizeContributor(value) {
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeContributor(item))
      .filter(Boolean)
      .join(' / ')
  }
  if (value && typeof value === 'object') {
    return normalizeContributor(value.name || value.label || value.value || Object.values(value))
  }
  return ''
}

function normalizeSkillPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return payload
  }

  const normalized = {
    ...payload,
    contributor: normalizeContributor(payload.contributor) || null,
  }

  if (Array.isArray(payload.version_history)) {
    normalized.version_history = payload.version_history.map((item) => ({
      ...item,
      contributor: normalizeContributor(item?.contributor) || null,
    }))
  }

  return normalized
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (authState.token) {
    headers.set('Authorization', `Bearer ${authState.token}`)
  }

  const isFormData = options.body instanceof FormData
  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })

  if (response.status === 204) {
    return null
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      clearSession()
    }
    throw new Error(payload.detail || '请求失败')
  }
  return payload
}

export function isAuthenticated() {
  return Boolean(authState.token && authState.user)
}

export function isAdmin() {
  return authState.user?.role === 'ADMIN'
}

export function getCurrentUser() {
  return authState.user
}

export function getUserDisplayName(user) {
  if (!user) {
    return ''
  }
  return user.display_name || user.username
}

export function setSession(token, user) {
  authState.token = token
  authState.user = user
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  authState.token = null
  authState.user = null
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USER_KEY)
}

export function getWorkspaceRoute() {
  return '/workspace'
}

export async function fetchPublicConfig() {
  if (publicConfigCache) {
    return publicConfigCache
  }

  if (!publicConfigRequest) {
    publicConfigRequest = request(buildUrl('/api/public-config'))
      .then((payload) => {
        publicConfigCache = payload
        return payload
      })
      .finally(() => {
        publicConfigRequest = null
      })
  }

  return publicConfigRequest
}

export async function fetchSkills(query, options = {}) {
  const payload = await request(buildUrl('/api/skills', { q: query, page: options.page, page_size: options.pageSize }))
  return {
    ...payload,
    local_items: (payload.local_items || []).map(normalizeSkillPayload),
    remote_items: (payload.remote_items || []).map(normalizeSkillPayload),
  }
}

export async function fetchSkill(source, slug) {
  return normalizeSkillPayload(await request(buildUrl(`/api/skills/${source}/${slug}`)))
}

export async function fetchLocalSkillVersion(slug, version) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/skills/local/${encodeURIComponent(slug)}/versions/${encodeURIComponent(version)}`)),
  )
}

export function login(payload) {
  return request(buildUrl('/api/auth/login'), {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function logout() {
  return request(buildUrl('/api/auth/logout'), { method: 'POST' })
}

export function fetchCurrentUser() {
  return request(buildUrl('/api/auth/me'))
}

export async function fetchWorkspaceSkills(query) {
  return (await request(buildUrl('/api/workspace/skills', { q: query }))).map(normalizeSkillPayload)
}

export async function fetchWorkspaceSkill(name) {
  return normalizeSkillPayload(await request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`)))
}

export async function createSkill(formData) {
  return normalizeSkillPayload(
    await request(buildUrl('/api/workspace/skills'), {
      method: 'POST',
      body: formData,
    }),
  )
}

export async function updateSkill(name, formData) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`), {
      method: 'PUT',
      body: formData,
    }),
  )
}

export function deleteSkill(name) {
  return request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`), {
    method: 'DELETE',
  })
}

export async function fetchUsers() {
  return await request(buildUrl('/api/admin/users'))
}

export async function createUser(payload) {
  return await request(buildUrl('/api/admin/users'), {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateUser(userId, payload) {
  return await request(buildUrl(`/api/admin/users/${encodeURIComponent(userId)}`), {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function resetUserPassword(userId, password) {
  return await request(buildUrl(`/api/admin/users/${encodeURIComponent(userId)}/password`), {
    method: 'PUT',
    body: JSON.stringify({ password }),
  })
}
