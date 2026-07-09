import { CliError } from './errors.js'
import { DEFAULT_REGISTRY } from './registry.js'

const VALUE_FLAGS = new Set(['--target', '--registry', '--token', '--version'])
const BOOLEAN_FLAGS = new Set(['--dry-run', '--json', '--force'])

export function parseArgs(argv) {
  const [command, subject, slug, ...rest] = argv
  if (command !== 'install' || subject !== 'collection' || !slug) {
    throw new CliError('用法：nexgo-skills install collection <slug> [--target codex] [--dry-run]', 2)
  }

  const options = {
    command,
    subject,
    slug,
    target: 'codex',
    registry: process.env.NEXGO_SKILLS_REGISTRY || DEFAULT_REGISTRY,
    token: process.env.NEXGO_SKILLS_TOKEN || '',
    version: '',
    dryRun: false,
    json: false,
    force: false,
  }

  for (let index = 0; index < rest.length; index += 1) {
    const flag = rest[index]
    if (BOOLEAN_FLAGS.has(flag)) {
      const key = flagToKey(flag)
      options[key] = true
      continue
    }
    if (VALUE_FLAGS.has(flag)) {
      const value = rest[index + 1]
      if (!value || value.startsWith('--')) {
        throw new CliError(`${flag} 需要提供值`, 2)
      }
      options[flagToKey(flag)] = value
      index += 1
      continue
    }
    throw new CliError(`未知参数：${flag}`, 2)
  }

  return options
}

function flagToKey(flag) {
  return flag.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())
}
