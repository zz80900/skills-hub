import { reactive } from 'vue'
import { buildEncryptedPassword } from './security'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'nexgo-skills-session-token'
const USER_KEY = 'nexgo-skills-session-user'
const AUTH_MODE_NONE = 'none'
const AUTH_MODE_OPTIONAL = 'optional'
const AUTH_MODE_REQUIRED = 'required'

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

function getRequestHeaders(options, includeAuth) {
  const headers = new Headers(options.headers || {})
  if (includeAuth && authState.token) {
    headers.set('Authorization', `Bearer ${authState.token}`)
  }
  return headers
}

function shouldResetHomeLocation() {
  const location = window.location
  if (location.pathname.startsWith('/skills/')) {
    return true
  }
  if (location.pathname !== '/') {
    return false
  }
  const params = new URLSearchParams(location.search)
  return ['skill', 'source', 'version'].some((key) => params.has(key))
}

function redirectToHome() {
  window.location.replace('/')
}

function redirectToLogin() {
  const location = window.location
  const currentPath = `${location.pathname}${location.search}${location.hash}`
  const loginUrl = new URL('/login', location.origin)
  if (currentPath && currentPath !== '/login') {
    loginUrl.searchParams.set('redirect', currentPath)
  }
  window.location.replace(`${loginUrl.pathname}${loginUrl.search}`)
}

function waitForNavigation() {
  return new Promise(() => {})
}

async function request(path, options = {}) {
  const { authMode = AUTH_MODE_REQUIRED, ...fetchOptions } = options
  const includeAuth = authMode !== AUTH_MODE_NONE && Boolean(authState.token)
  const headers = getRequestHeaders(fetchOptions, includeAuth)

  const isFormData = fetchOptions.body instanceof FormData
  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, {
    ...fetchOptions,
    headers,
  })

  if (response.status === 204) {
    return null
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      clearSession()
      if (authMode === AUTH_MODE_OPTIONAL && includeAuth) {
        if (shouldResetHomeLocation()) {
          redirectToHome()
          return waitForNavigation()
        }
        return request(path, {
          ...fetchOptions,
          authMode,
        })
      }
      if (
        authMode === AUTH_MODE_REQUIRED
        && (window.location.pathname.startsWith('/workspace') || window.location.pathname.startsWith('/admin'))
      ) {
        redirectToLogin()
        return waitForNavigation()
      }
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
    publicConfigRequest = request(buildUrl('/api/public-config'), { authMode: AUTH_MODE_OPTIONAL })
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
  const payload = await request(buildUrl('/api/skills', { q: query, page: options.page, page_size: options.pageSize }), {
    authMode: AUTH_MODE_OPTIONAL,
  })
  return {
    ...payload,
    local_items: (payload.local_items || []).map(normalizeSkillPayload),
    remote_items: (payload.remote_items || []).map(normalizeSkillPayload),
  }
}

export async function fetchSkill(source, slug) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/skills/${source}/${slug}`), {
      authMode: AUTH_MODE_OPTIONAL,
    }),
  )
}

export async function login(payload) {
  const encrypted = await buildEncryptedPassword(payload.password, 'login', {
    username: payload.username,
  })
  return request(buildUrl('/api/auth/login'), {
    method: 'POST',
    authMode: AUTH_MODE_NONE,
    body: JSON.stringify({
      username: payload.username,
      ...encrypted,
    }),
  })
}

export function logout() {
  return request(buildUrl('/api/auth/logout'), { method: 'POST', authMode: AUTH_MODE_REQUIRED })
}

export function fetchCurrentUser() {
  return request(buildUrl('/api/auth/me'), { authMode: AUTH_MODE_REQUIRED })
}

export async function fetchWorkspaceSkills(query) {
  return (
    await request(buildUrl('/api/workspace/skills', { q: query }), { authMode: AUTH_MODE_REQUIRED })
  ).map(normalizeSkillPayload)
}

export async function fetchWorkspaceSkill(name) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`), { authMode: AUTH_MODE_REQUIRED }),
  )
}

export async function createSkill(formData) {
  return normalizeSkillPayload(
    await request(buildUrl('/api/workspace/skills'), {
      method: 'POST',
      authMode: AUTH_MODE_REQUIRED,
      body: formData,
    }),
  )
}

export async function updateSkill(name, formData) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`), {
      method: 'PUT',
      authMode: AUTH_MODE_REQUIRED,
      body: formData,
    }),
  )
}

export function deleteSkill(name) {
  return request(buildUrl(`/api/workspace/skills/${encodeURIComponent(name)}`), {
    method: 'DELETE',
    authMode: AUTH_MODE_REQUIRED,
  })
}

export async function fetchUsers(query, options = {}) {
  return await request(
    buildUrl('/api/admin/users', {
      q: query,
      page: options.page,
      page_size: options.pageSize,
    }),
    { authMode: AUTH_MODE_REQUIRED },
  )
}

export async function createUser(payload) {
  const body = { ...payload }
  if (body.password) {
    const encrypted = await buildEncryptedPassword(body.password, 'admin_create_user', {
      username: body.username,
    })
    delete body.password
    Object.assign(body, encrypted)
  }
  return await request(buildUrl('/api/admin/users'), {
    method: 'POST',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify(body),
  })
}

export async function fetchAdminGroups() {
  return await request(buildUrl('/api/admin/groups'), { authMode: AUTH_MODE_REQUIRED })
}

export async function createGroup(payload) {
  return await request(buildUrl('/api/admin/groups'), {
    method: 'POST',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify(payload),
  })
}

export async function updateGroup(groupId, payload) {
  return await request(buildUrl(`/api/admin/groups/${encodeURIComponent(groupId)}`), {
    method: 'PUT',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify(payload),
  })
}

export async function deleteGroup(groupId) {
  return await request(buildUrl(`/api/admin/groups/${encodeURIComponent(groupId)}`), {
    method: 'DELETE',
    authMode: AUTH_MODE_REQUIRED,
  })
}

export async function fetchWorkspaceGroups() {
  return await request(buildUrl('/api/workspace/groups'), { authMode: AUTH_MODE_REQUIRED })
}

export async function fetchGroupOptions() {
  return await request(buildUrl('/api/workspace/groups/options'), { authMode: AUTH_MODE_REQUIRED })
}

export async function fetchGroupMemberOptions() {
  return await request(buildUrl('/api/workspace/groups/member-options'), { authMode: AUTH_MODE_REQUIRED })
}

export async function updateGroupMembers(groupId, userIds) {
  return await request(buildUrl(`/api/workspace/groups/${encodeURIComponent(groupId)}/members`), {
    method: 'PUT',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify({ user_ids: userIds }),
  })
}

export async function addGroupMember(groupId, userId) {
  return await request(buildUrl(`/api/workspace/groups/${encodeURIComponent(groupId)}/members`), {
    method: 'POST',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify({ user_id: userId }),
  })
}

export async function removeGroupMember(groupId, userId) {
  return await request(buildUrl(`/api/workspace/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`), {
    method: 'DELETE',
    authMode: AUTH_MODE_REQUIRED,
  })
}

export async function updateUser(userId, payload) {
  return await request(buildUrl(`/api/admin/users/${encodeURIComponent(userId)}`), {
    method: 'PUT',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify(payload),
  })
}

export async function resetUserPassword(userId, password) {
  const encrypted = await buildEncryptedPassword(password, 'admin_reset_password', {
    user_id: userId,
  })
  return await request(buildUrl(`/api/admin/users/${encodeURIComponent(userId)}/password`), {
    method: 'PUT',
    authMode: AUTH_MODE_REQUIRED,
    body: JSON.stringify(encrypted),
  })
}
