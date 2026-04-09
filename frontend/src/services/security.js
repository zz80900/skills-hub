const CHALLENGE_ENDPOINT = '/api/auth/challenge'

function generateNonce() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

function generateClientTs() {
  return Math.floor(Date.now() / 1000)
}

function pemToCryptoKey(pem) {
  const pemHeader = '-----BEGIN PUBLIC KEY-----'
  const pemFooter = '-----END PUBLIC KEY-----'
  const pemContents = pem.replace(pemHeader, '').replace(pemFooter, '').replace(/\s/g, '')
  const binary = atob(pemContents)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return crypto.subtle.importKey('spki', bytes, { name: 'RSA-OAEP', hash: 'SHA-256' }, true, ['encrypt'])
}

function buildPayload(params) {
  return JSON.stringify({
    username: params.username || '',
    user_id: params.user_id || '',
    password: params.password,
    challenge_id: params.challenge_id,
    server_nonce: params.server_nonce,
    client_ts: params.client_ts,
    nonce: params.nonce,
    purpose: params.purpose,
  })
}

async function encryptPayload(plaintext, publicKeyPem) {
  const cryptoKey = await pemToCryptoKey(publicKeyPem)
  const encoded = new TextEncoder().encode(plaintext)
  const encrypted = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, cryptoKey, encoded)
  return btoa(String.fromCharCode(...new Uint8Array(encrypted)))
}

let challengeCache = null
let challengeRequest = null

async function fetchChallenge() {
  if (challengeCache && !challengeCache.expired) {
    return challengeCache
  }

  if (!challengeRequest) {
    challengeRequest = fetch(CHALLENGE_ENDPOINT)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error('获取挑战参数失败')
        }
        const data = await res.json()
        const expiresAt = Date.now() + data.expires_in_seconds * 1000
        challengeCache = {
          challenge_id: data.challenge_id,
          public_key_pem: data.public_key_pem,
          server_nonce: data.server_nonce,
          expires_in_seconds: data.expires_in_seconds,
          algorithm: data.algorithm,
          expired: false,
          expiresAt,
        }

        setTimeout(() => {
          if (challengeCache) {
            challengeCache.expired = true
          }
          challengeCache = null
          challengeRequest = null
        }, data.expires_in_seconds * 1000)

        return challengeCache
      })
      .finally(() => {
        challengeRequest = null
      })
  }

  return challengeRequest
}

function invalidateChallenge() {
  challengeCache = null
  challengeRequest = null
}

export async function buildEncryptedPassword(password, purpose, extraParams = {}) {
  const challenge = await fetchChallenge()
  const nonce = generateNonce()
  const clientTs = generateClientTs()

  const params = {
    password,
    challenge_id: challenge.challenge_id,
    server_nonce: challenge.server_nonce,
    client_ts: clientTs,
    nonce,
    purpose,
    ...extraParams,
  }

  const plaintext = buildPayload(params)
  const encrypted = await encryptPayload(plaintext, challenge.public_key_pem)

  invalidateChallenge()

  return {
    encrypted_password: encrypted,
    challenge_id: challenge.challenge_id,
    client_ts: clientTs,
    nonce,
  }
}
