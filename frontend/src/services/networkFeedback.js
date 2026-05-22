import { notifyError, notifySuccess } from './feedback'

const FAILURE_NOTICE_INTERVAL_MS = 30000

let networkIssueActive = false
let lastFailureNoticeAt = 0

export function reportNetworkFailure(message) {
  networkIssueActive = true

  const now = Date.now()
  if (now - lastFailureNoticeAt < FAILURE_NOTICE_INTERVAL_MS) {
    return
  }

  lastFailureNoticeAt = now
  notifyError(message, {
    title: '网络访问失败',
    duration: 5200,
  })
}

export function reportNetworkSuccess() {
  if (!networkIssueActive) {
    return
  }

  networkIssueActive = false
  lastFailureNoticeAt = 0
  notifySuccess('网络访问已恢复，可以继续操作。', {
    title: '连接已恢复',
    duration: 2600,
  })
}
