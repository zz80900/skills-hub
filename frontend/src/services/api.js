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

export function fetchSkills(query, options = {}) {
  return request(buildUrl('/api/skills', { q: query, page: options.page, page_size: options.pageSize }))
}

export function fetchSkill(source, slug) {
  return request(buildUrl(`/api/skills/${source}/${slug}`))
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

export function fetchAdminSkills(query) {
  return request(buildUrl('/api/admin/skills', { q: query }))
}

export function fetchAdminSkill(name) {
  return request(buildUrl(`/api/admin/skills/${name}`))
}

export function createSkill(formData) {
  return request(buildUrl('/api/admin/skills'), {
    method: 'POST',
    body: formData,
  })
}

export function updateSkill(name, formData) {
  return request(buildUrl(`/api/admin/skills/${name}`), {
    method: 'PUT',
    body: formData,
  })
}
