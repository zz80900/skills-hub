export const DEFAULT_REGISTRY = 'https://skills.nexgoglobal.com'

export function normalizeRegistryUrl(registry) {
  const normalized = String(registry || '').trim() || DEFAULT_REGISTRY
  return normalized.endsWith('/') ? normalized : `${normalized}/`
}
