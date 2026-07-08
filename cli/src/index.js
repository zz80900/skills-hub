import { parseArgs } from './args.js'
import { CliError } from './errors.js'
import { installCollection } from './installCollection.js'

export async function main(argv) {
  const options = parseArgs(argv)
  try {
    const result = await installCollection(options)
    if (options.json) {
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
      return
    }
    printHumanResult(result)
    if (result.status === 'blocked') {
      process.exitCode = 3
    }
  } catch (error) {
    if (options.json) {
      process.stdout.write(`${JSON.stringify(errorToJson(error), null, 2)}\n`)
      process.exitCode = error?.exitCode || 1
      return
    }
    throw error
  }
}

function printHumanResult(result) {
  if (result.status === 'dry-run' || result.status === 'blocked') {
    process.stdout.write(`Skill 集合：${result.collection}@${result.version}\n`)
    process.stdout.write(`目标：${result.target} (${result.targetDir})\n`)
    for (const item of result.items) {
      process.stdout.write(`- ${item.name}: ${item.action}\n`)
    }
    if (result.conflicts.length) {
      process.stdout.write('冲突：\n')
      for (const conflict of result.conflicts) {
        process.stdout.write(`- ${conflict.name}: ${conflict.reason}\n`)
      }
    }
    return
  }

  process.stdout.write(`已安装 Skill 集合 ${result.collection}@${result.version} 到 ${result.target}\n`)
  for (const item of result.items) {
    process.stdout.write(`- ${item.name}: ${item.action}\n`)
  }
}

function errorToJson(error) {
  if (error instanceof CliError) {
    return {
      status: 'error',
      message: error.message,
      details: error.details || {},
    }
  }
  return {
    status: 'error',
    message: error?.message || '命令执行失败',
  }
}
