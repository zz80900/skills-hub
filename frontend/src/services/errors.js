export const NETWORK_ACCESS_ERROR_MESSAGE = '网络访问失败，请关闭代理/VPN，并使用新国都内部网络访问。'

export function createNetworkAccessError(cause) {
  const error = new Error(NETWORK_ACCESS_ERROR_MESSAGE)
  error.cause = cause
  return error
}
