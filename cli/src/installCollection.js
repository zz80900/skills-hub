import fs from 'node:fs/promises'
import path from 'node:path'

import { resolveTargetAdapter } from './adapters.js'
import { CliError } from './errors.js'
import {
  checksumDirectory,
  copyDirectory,
  pathExists,
  readJsonFile,
  removePath,
  writeJsonFile,
  writeSkillDirectory,
} from './files.js'
import { normalizeRegistryUrl } from './registry.js'
import { verifyPackageAgainstManifest } from './zip.js'

export async function installCollection(options) {
  const manifestUrl = buildManifestUrl(options.registry, options.slug, options.version)
  const manifest = await fetchJson(manifestUrl, options.token)
  const packageUrl = resolveRegistryUrl(options.registry, manifest.package_url)
  const packageBuffer = await fetchBuffer(packageUrl, options.token)
  const parsedZip = verifyPackageAgainstManifest(manifest, packageBuffer)
  const adapter = resolveTargetAdapter(options.target)
  const plan = await planCollectionInstall({
    adapter,
    manifest,
    parsedZip,
    force: options.force,
  })

  if (options.dryRun) {
    return {
      status: plan.conflicts.length ? 'blocked' : 'dry-run',
      collection: manifest.slug,
      version: manifest.version,
      target: adapter.name,
      targetDir: adapter.skillsDir,
      items: plan.items,
      conflicts: plan.conflicts,
    }
  }

  if (plan.conflicts.length) {
    throw new CliError('安装前检查失败：存在未管理的目标目录冲突', 3, {
      conflicts: plan.conflicts,
    })
  }

  return commitPlan({
    adapter,
    manifest,
    parsedZip,
    plan,
  })
}

export async function planCollectionInstall({ adapter, manifest, parsedZip, force = false }) {
  const targetRoot = path.resolve(adapter.skillsDir)
  const nexgoRoot = path.join(targetRoot, '.nexgo')
  const installedPath = path.join(nexgoRoot, 'installed.json')
  const installed = await readJsonFile(installedPath, { items: {} })
  const parsedItems = new Map(parsedZip.items.map((item) => [item.path, item]))
  const items = []
  const conflicts = []

  for (const manifestItem of manifest.items) {
    const zipItem = parsedItems.get(manifestItem.path)
    const targetDir = path.resolve(targetRoot, manifestItem.path)
    if (!targetDir.startsWith(`${targetRoot}${path.sep}`)) {
      conflicts.push({ name: manifestItem.name, reason: 'unsafe-target-path' })
      continue
    }

    const exists = await pathExists(targetDir)
    const managedRecord = installed.items?.[manifestItem.name]
    let action = 'create'
    let existingChecksum = ''
    if (exists) {
      existingChecksum = await checksumDirectory(targetDir)
      if (existingChecksum === manifestItem.sha256) {
        action = 'unchanged'
      } else if (managedRecord || force) {
        action = 'overwrite'
      } else {
        action = 'conflict'
        conflicts.push({ name: manifestItem.name, path: targetDir, reason: 'unmanaged-existing-directory' })
      }
    }

    items.push({
      name: manifestItem.name,
      path: manifestItem.path,
      targetPath: targetDir,
      action,
      sha256: manifestItem.sha256,
      existingChecksum,
      managed: Boolean(managedRecord),
      files: zipItem.files,
    })
  }

  return { items, conflicts, installed, installedPath, targetRoot, nexgoRoot }
}

export async function commitPlan({ adapter, manifest, plan }) {
  const transactionId = `${Date.now()}-${process.pid}`
  const backupRoot = path.join(plan.nexgoRoot, 'backups', transactionId)
  const transactionPath = path.join(plan.nexgoRoot, 'transactions', `${transactionId}.json`)
  const completed = []

  try {
    await fs.mkdir(plan.nexgoRoot, { recursive: true })
    for (const item of plan.items) {
      if (item.action === 'unchanged') {
        continue
      }
      const backupDir = path.join(backupRoot, item.name)
      const existed = await pathExists(item.targetPath)
      if (existed) {
        await copyDirectory(item.targetPath, backupDir)
      }
      await writeSkillDirectory(item.targetPath, item.files)
      completed.push({
        name: item.name,
        targetPath: item.targetPath,
        action: item.action,
        backupDir,
        existed,
      })
      const writtenChecksum = await checksumDirectory(item.targetPath)
      if (writtenChecksum !== item.sha256) {
        throw new CliError(`安装后校验失败：${item.name}`)
      }
      plan.installed.items[item.name] = {
        collection: manifest.slug,
        version: manifest.version,
        target: adapter.name,
        path: item.targetPath,
        checksum: item.sha256,
        managedBy: 'nexgo',
        updatedAt: new Date().toISOString(),
      }
    }

    await writeJsonFile(plan.installedPath, plan.installed)
    await writeJsonFile(transactionPath, {
      id: transactionId,
      collection: manifest.slug,
      version: manifest.version,
      target: adapter.name,
      targetDir: adapter.skillsDir,
      items: plan.items.map((item) => ({
        name: item.name,
        path: item.path,
        action: item.action,
        sha256: item.sha256,
      })),
      createdAt: new Date().toISOString(),
    })

    return {
      status: 'installed',
      collection: manifest.slug,
      version: manifest.version,
      target: adapter.name,
      targetDir: adapter.skillsDir,
      transaction: transactionId,
      items: plan.items.map(({ files, ...item }) => item),
      conflicts: [],
    }
  } catch (error) {
    await rollbackCompleted(completed)
    if (error instanceof CliError) {
      throw error
    }
    throw new CliError(error?.message || 'Skill 集合安装失败，已回滚')
  }
}

async function rollbackCompleted(completed) {
  for (const item of [...completed].reverse()) {
    await removePath(item.targetPath)
    if (item.existed) {
      await copyDirectory(item.backupDir, item.targetPath)
    }
  }
}

async function fetchJson(url, token) {
  const response = await fetch(url, {
    headers: buildHeaders(token),
  })
  if (!response.ok) {
    throw new CliError(`获取 Skill 集合 manifest 失败：${response.status}`)
  }
  return response.json()
}

async function fetchBuffer(url, token) {
  const response = await fetch(url, {
    headers: buildHeaders(token),
  })
  if (!response.ok) {
    throw new CliError(`下载 Skill 集合 ZIP 失败：${response.status}`)
  }
  return Buffer.from(await response.arrayBuffer())
}

function buildHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function buildManifestUrl(registry, slug, version) {
  const url = new URL(`/api/collections/${encodeURIComponent(slug)}/manifest`, normalizeRegistryUrl(registry))
  if (version) {
    url.searchParams.set('version', version)
  }
  return url.toString()
}

function resolveRegistryUrl(registry, value) {
  return new URL(value, normalizeRegistryUrl(registry)).toString()
}
