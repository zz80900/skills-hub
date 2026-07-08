import crypto from 'node:crypto'
import zlib from 'node:zlib'

import { CliError } from './errors.js'

const EOCD_SIGNATURE = 0x06054b50
const CENTRAL_SIGNATURE = 0x02014b50
const LOCAL_SIGNATURE = 0x04034b50

export function checksumSkillFiles(files) {
  const hash = crypto.createHash('sha256')
  for (const file of [...files].sort((a, b) => a.path.localeCompare(b.path))) {
    hash.update(file.path, 'utf8')
    hash.update(Buffer.from([0]))
    hash.update(file.content)
    hash.update(Buffer.from([0]))
  }
  return hash.digest('hex')
}

export function parseCollectionZip(buffer) {
  const entries = readZipEntries(buffer)
  const rootNames = new Map()
  const skills = new Map()

  for (const entry of entries) {
    const normalizedName = normalizeArchiveName(entry.name)
    if (isUnsafeArchivePath(normalizedName)) {
      throw new CliError('Skill 集合 ZIP 包含不安全路径')
    }
    const trimmedName = normalizedName.replace(/\/+$/, '')
    if (!trimmedName) {
      continue
    }
    const slashIndex = trimmedName.indexOf('/')
    const root = slashIndex === -1 ? trimmedName : trimmedName.slice(0, slashIndex)
    const relativePath = slashIndex === -1 ? '' : trimmedName.slice(slashIndex + 1)
    const normalizedRoot = root.toLowerCase()
    const existingRoot = rootNames.get(normalizedRoot)
    if (existingRoot && existingRoot !== root) {
      throw new CliError('Skill 集合 ZIP 包含重复的 Skill 目录名称')
    }
    rootNames.set(normalizedRoot, root)
    if (!skills.has(root)) {
      skills.set(root, [])
    }

    if (entry.isDirectory) {
      continue
    }
    if (!relativePath) {
      throw new CliError('Skill 集合 ZIP 根目录只能包含 Skill 目录，不能包含普通文件')
    }
    skills.get(root).push({
      path: relativePath,
      content: entry.content,
    })
  }

  if (!skills.size) {
    throw new CliError('Skill 集合 ZIP 至少需要包含一个 Skill 目录')
  }

  const items = []
  for (const [root, files] of [...skills.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const skillMd = files.find((file) => file.path === 'SKILL.md')
    if (!skillMd || !skillMd.content.toString('utf8').trim()) {
      throw new CliError(`Skill 集合 ZIP 中的 Skill 目录缺少非空 SKILL.md: ${root}`)
    }
    items.push({
      name: root,
      path: root,
      sha256: checksumSkillFiles(files),
      fileCount: files.length,
      files,
    })
  }
  return { items }
}

export function verifyPackageAgainstManifest(manifest, buffer) {
  if (!manifest || manifest.schema_version !== 'nexgo.collection.v1') {
    throw new CliError('Skill 集合 manifest schema_version 无效')
  }
  if (!Array.isArray(manifest.items) || !manifest.items.length) {
    throw new CliError('Skill 集合 manifest 缺少 items')
  }

  const parsed = parseCollectionZip(buffer)
  const zipItems = new Map(parsed.items.map((item) => [item.path, item]))
  for (const manifestItem of manifest.items) {
    const zipItem = zipItems.get(manifestItem.path)
    if (!zipItem) {
      throw new CliError(`Skill 集合 ZIP 缺少 manifest 条目：${manifestItem.path}`)
    }
    if (zipItem.sha256 !== manifestItem.sha256) {
      throw new CliError(`Skill 集合 ZIP checksum 不匹配：${manifestItem.path}`)
    }
  }
  return parsed
}

function readZipEntries(buffer) {
  const eocdOffset = findEndOfCentralDirectory(buffer)
  const entryCount = buffer.readUInt16LE(eocdOffset + 10)
  const centralDirectoryOffset = buffer.readUInt32LE(eocdOffset + 16)
  const entries = []
  let offset = centralDirectoryOffset

  for (let index = 0; index < entryCount; index += 1) {
    if (buffer.readUInt32LE(offset) !== CENTRAL_SIGNATURE) {
      throw new CliError('ZIP 中央目录无效')
    }
    const flags = buffer.readUInt16LE(offset + 8)
    if (flags & 0x01) {
      throw new CliError('不支持加密 ZIP')
    }
    const compression = buffer.readUInt16LE(offset + 10)
    const compressedSize = buffer.readUInt32LE(offset + 20)
    const fileNameLength = buffer.readUInt16LE(offset + 28)
    const extraLength = buffer.readUInt16LE(offset + 30)
    const commentLength = buffer.readUInt16LE(offset + 32)
    const localHeaderOffset = buffer.readUInt32LE(offset + 42)
    const name = buffer.subarray(offset + 46, offset + 46 + fileNameLength).toString('utf8')
    const content = readLocalFile(buffer, localHeaderOffset, compressedSize, compression)
    entries.push({
      name,
      isDirectory: name.endsWith('/'),
      content,
    })
    offset += 46 + fileNameLength + extraLength + commentLength
  }

  return entries
}

function readLocalFile(buffer, offset, compressedSize, compression) {
  if (buffer.readUInt32LE(offset) !== LOCAL_SIGNATURE) {
    throw new CliError('ZIP 本地文件头无效')
  }
  const fileNameLength = buffer.readUInt16LE(offset + 26)
  const extraLength = buffer.readUInt16LE(offset + 28)
  const dataOffset = offset + 30 + fileNameLength + extraLength
  const compressed = buffer.subarray(dataOffset, dataOffset + compressedSize)
  if (compression === 0) {
    return Buffer.from(compressed)
  }
  if (compression === 8) {
    return zlib.inflateRawSync(compressed)
  }
  throw new CliError(`不支持的 ZIP 压缩方法：${compression}`)
}

function findEndOfCentralDirectory(buffer) {
  const minOffset = Math.max(0, buffer.length - 65557)
  for (let offset = buffer.length - 22; offset >= minOffset; offset -= 1) {
    if (buffer.readUInt32LE(offset) === EOCD_SIGNATURE) {
      return offset
    }
  }
  throw new CliError('无效的 ZIP 压缩包')
}

function normalizeArchiveName(name) {
  return String(name || '').replace(/\\/g, '/')
}

function isUnsafeArchivePath(name) {
  if (!name || name.startsWith('/') || /^[A-Za-z]:/.test(name)) {
    return true
  }
  const parts = name.replace(/\/+$/, '').split('/')
  return parts.some((part) => !part || part === '.' || part === '..')
}
