import os from 'node:os'
import path from 'node:path'

import { CliError } from './errors.js'

export function resolveTargetAdapter(targetName) {
  const normalizedTarget = (targetName || 'codex').trim().toLowerCase()
  if (normalizedTarget === 'codex') {
    const root = process.env.CODEX_HOME || path.join(os.homedir(), '.codex')
    return {
      name: 'codex',
      skillsDir: path.join(root, 'skills'),
    }
  }
  if (normalizedTarget === 'claude-code') {
    const root = process.env.CLAUDE_CODE_HOME || process.env.CLAUDE_HOME || path.join(os.homedir(), '.claude')
    return {
      name: 'claude-code',
      skillsDir: path.join(root, 'skills'),
    }
  }
  throw new CliError(`不支持的安装目标：${targetName}`, 2, { target: targetName })
}
