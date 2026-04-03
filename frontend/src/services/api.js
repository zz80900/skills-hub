const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'ssc-skills-admin-token'

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
  const token = getToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
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
    throw new Error(payload.detail || '请求失败')
  }
  return payload
}

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY)
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
  return request(buildUrl('/api/admin/login'), {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function logout() {
  return request(buildUrl('/api/admin/logout'), { method: 'POST' })
}

export async function fetchAdminSkills(query) {
  return (await request(buildUrl('/api/admin/skills', { q: query }))).map(normalizeSkillPayload)
}

export async function fetchAdminSkill(name) {
  return normalizeSkillPayload(await request(buildUrl(`/api/admin/skills/${encodeURIComponent(name)}`)))
}

export async function createSkill(formData) {
  return normalizeSkillPayload(
    await request(buildUrl('/api/admin/skills'), {
      method: 'POST',
      body: formData,
    }),
  )
}

export async function updateSkill(name, formData) {
  return normalizeSkillPayload(
    await request(buildUrl(`/api/admin/skills/${encodeURIComponent(name)}`), {
      method: 'PUT',
      body: formData,
    }),
  )
}

export function deleteSkill(name) {
  return request(buildUrl(`/api/admin/skills/${encodeURIComponent(name)}`), {
    method: 'DELETE',
  })
}
