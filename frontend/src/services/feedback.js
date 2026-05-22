import { reactive } from 'vue'

const STORAGE_KEY = 'nexgo-skills-pending-notice'

export const notices = reactive([])

let nextId = 0

function normalizeTone(tone) {
  return ['success', 'error', 'warning', 'info'].includes(tone) ? tone : 'info'
}

function scheduleDismiss(id, duration) {
  if (duration === 0) {
    return
  }
  window.setTimeout(() => {
    dismissNotice(id)
  }, duration)
}

export function dismissNotice(id) {
  const index = notices.findIndex((notice) => notice.id === id)
  if (index >= 0) {
    notices.splice(index, 1)
  }
}

export function pushNotice(payload) {
  const notice = {
    id: ++nextId,
    tone: normalizeTone(payload.tone),
    title: typeof payload.title === 'string' ? payload.title.trim() : '',
    message: typeof payload.message === 'string' ? payload.message.trim() : '',
    duration: typeof payload.duration === 'number' ? payload.duration : 3200,
  }
  notices.unshift(notice)
  scheduleDismiss(notice.id, notice.duration)
  return notice.id
}

export function notifySuccess(message, options = {}) {
  return pushNotice({ ...options, tone: 'success', message, duration: options.duration ?? 2600 })
}

export function notifyError(message, options = {}) {
  return pushNotice({ ...options, tone: 'error', message, duration: options.duration ?? 3800 })
}

export function notifyInfo(message, options = {}) {
  return pushNotice({ ...options, tone: 'info', message, duration: options.duration ?? 3200 })
}

export function stashNotice(payload) {
  window.sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      tone: normalizeTone(payload.tone),
      title: typeof payload.title === 'string' ? payload.title : '',
      message: typeof payload.message === 'string' ? payload.message : '',
      duration: typeof payload.duration === 'number' ? payload.duration : 3200,
    }),
  )
}

export function consumeStashedNotice() {
  const raw = window.sessionStorage.getItem(STORAGE_KEY)
  if (!raw) {
    return null
  }
  window.sessionStorage.removeItem(STORAGE_KEY)
  try {
    const payload = JSON.parse(raw)
    if (!payload || typeof payload !== 'object') {
      return null
    }
    return {
      tone: normalizeTone(payload.tone),
      title: typeof payload.title === 'string' ? payload.title : '',
      message: typeof payload.message === 'string' ? payload.message : '',
      duration: typeof payload.duration === 'number' ? payload.duration : 3200,
    }
  } catch {
    return null
  }
}
