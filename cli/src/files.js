import fs from 'node:fs/promises'
import path from 'node:path'

import { checksumSkillFiles } from './zip.js'

export async function pathExists(targetPath) {
  try {
    await fs.access(targetPath)
    return true
  } catch {
    return false
  }
}

export async function readJsonFile(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'))
  } catch {
    return fallback
  }
}

export async function writeJsonFile(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true })
  await fs.writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`)
}

export async function removePath(targetPath) {
  await fs.rm(targetPath, { recursive: true, force: true })
}

export async function copyDirectory(sourceDir, targetDir) {
  await removePath(targetDir)
  await fs.mkdir(path.dirname(targetDir), { recursive: true })
  await fs.cp(sourceDir, targetDir, { recursive: true })
}

export async function writeSkillDirectory(targetDir, files) {
  await removePath(targetDir)
  for (const file of files) {
    const outputPath = path.join(targetDir, ...file.path.split('/'))
    await fs.mkdir(path.dirname(outputPath), { recursive: true })
    await fs.writeFile(outputPath, file.content)
  }
}

export async function checksumDirectory(directory) {
  const files = []
  await collectFiles(directory, '', files)
  return checksumSkillFiles(files)
}

async function collectFiles(root, relativeRoot, files) {
  const entries = await fs.readdir(path.join(root, relativeRoot), { withFileTypes: true })
  for (const entry of entries) {
    const relativePath = relativeRoot ? `${relativeRoot}/${entry.name}` : entry.name
    if (entry.isDirectory()) {
      await collectFiles(root, relativePath, files)
      continue
    }
    if (!entry.isFile()) {
      continue
    }
    files.push({
      path: relativePath,
      content: await fs.readFile(path.join(root, ...relativePath.split('/'))),
    })
  }
}
