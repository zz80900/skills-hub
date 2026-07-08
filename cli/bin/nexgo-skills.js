#!/usr/bin/env node

import { main } from '../src/index.js'

main(process.argv.slice(2)).catch((error) => {
  const message = error?.message || '命令执行失败'
  process.stderr.write(`${message}\n`)
  process.exitCode = error?.exitCode || 1
})
