import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { resolveTargetAdapter } from '../src/adapters.js'
import { parseArgs } from '../src/args.js'
import { commitPlan, installCollection } from '../src/installCollection.js'
import { checksumSkillFiles, parseCollectionZip, verifyPackageAgainstManifest } from '../src/zip.js'

test('默认使用线上 Skill 集合服务地址', () => {
  const originalRegistry = process.env.NEXGO_SKILLS_REGISTRY
  delete process.env.NEXGO_SKILLS_REGISTRY
  try {
    const options = parseArgs(['install', 'collection', 'demo'])
    assert.equal(options.registry, 'https://skills.nexgoglobal.com')
  } finally {
    if (originalRegistry === undefined) {
      delete process.env.NEXGO_SKILLS_REGISTRY
    } else {
      process.env.NEXGO_SKILLS_REGISTRY = originalRegistry
    }
  }
})

test('命令行 token 优先于环境变量', () => {
  const restoreToken = setEnv('NEXGO_SKILLS_TOKEN', 'ns-env-token')
  try {
    assert.equal(parseArgs(['install', 'collection', 'demo']).token, 'ns-env-token')
    assert.equal(
      parseArgs(['install', 'collection', 'demo', '--token', 'ns-cli-token']).token,
      'ns-cli-token',
    )
  } finally {
    restoreToken()
  }
})

test('解析 Skill 集合 ZIP 并把 cmd 当作普通内容', () => {
  const zip = makeZip({
    'alpha/SKILL.md': '# alpha',
    'alpha/cmd': 'echo first\necho second',
    'alpha/references/a.md': 'A',
  })
  const parsed = parseCollectionZip(zip)

  assert.equal(parsed.items.length, 1)
  assert.equal(parsed.items[0].name, 'alpha')
  assert.equal(parsed.items[0].fileCount, 3)
  assert.ok(parsed.items[0].sha256)
})

test('checksum 排序与后端 manifest 生成保持一致', () => {
  assert.equal(
    checksumSkillFiles([
      { path: 'cmd', content: Buffer.from('echo ordinary') },
      { path: 'SKILL.md', content: Buffer.from('# alpha') },
    ]),
    'b5ae4ae431fb4aaafc6990caca91773c95995f5486185a6bc4b3eeeb293b9f0a',
  )
})

test('manifest checksum 不匹配时拒绝安装包', () => {
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  assert.throws(
    () => verifyPackageAgainstManifest({
      schema_version: 'nexgo.collection.v1',
      slug: 'demo',
      version: '1.0.0',
      items: [{ name: 'alpha', path: 'alpha', sha256: 'bad' }],
    }, zip),
    /checksum 不匹配/,
  )
})

test('dry-run 输出计划且不写入目标目录', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  const manifest = buildManifest('demo', zip)
  const registry = await startRegistry(manifest, zip)

  try {
    const result = await installCollection({
      slug: 'demo',
      registry: registry.url,
      token: '',
      version: '',
      target: 'codex',
      dryRun: true,
      json: true,
      force: false,
    })

    assert.equal(result.status, 'dry-run')
    assert.equal(result.items[0].action, 'create')
    assert.equal(await exists(path.join(workspace, 'codex-home', 'skills', 'alpha')), false)
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('公开集合安装不发送 Authorization', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  const manifest = buildManifest('demo', zip)
  const registry = await startAuthRegistry(manifest, zip, { expectedToken: '' })

  try {
    const result = await installCollection({
      slug: 'demo',
      registry: registry.url,
      token: '',
      version: '',
      target: 'codex',
      dryRun: true,
      json: true,
      force: false,
    })

    assert.equal(result.status, 'dry-run')
    assert.deepEqual(registry.requests.map((request) => request.authorization), [undefined, undefined])
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('manifest 和 package 请求发送同一个 Bearer token', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const token = 'ns-automation-token'
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  const manifest = buildManifest('demo', zip)
  const registry = await startAuthRegistry(manifest, zip, { expectedToken: token })

  try {
    const result = await installCollection({
      slug: 'demo',
      registry: registry.url,
      token,
      version: '',
      target: 'codex',
      dryRun: true,
      json: true,
      force: false,
    })

    assert.equal(result.status, 'dry-run')
    assert.deepEqual(
      registry.requests.map((request) => request.authorization),
      [`Bearer ${token}`, `Bearer ${token}`],
    )
    assert.deepEqual(
      registry.requests.map((request) => request.path),
      ['/api/collections/demo/manifest', '/packages/demo.zip'],
    )
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('401 不匿名重试且错误信息不泄露 token', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const invalidToken = 'ns-invalid-secret-token'
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  const manifest = buildManifest('demo', zip)
  const registry = await startAuthRegistry(manifest, zip, { expectedToken: 'ns-valid-token' })

  try {
    let receivedError
    try {
      await installCollection({
        slug: 'demo',
        registry: registry.url,
        token: invalidToken,
        version: '',
        target: 'codex',
        dryRun: true,
        json: true,
        force: false,
      })
    } catch (error) {
      receivedError = error
    }

    assert.ok(receivedError)
    assert.match(receivedError.message, /manifest 失败：401/)
    assert.equal(receivedError.message.includes(invalidToken), false)
    assert.deepEqual(registry.requests, [{
      path: '/api/collections/demo/manifest',
      authorization: `Bearer ${invalidToken}`,
    }])
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('成功事务会复制内容并记录 managed metadata', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const zip = makeZip({
    'alpha/SKILL.md': '# alpha',
    'alpha/cmd': 'echo ordinary',
  })
  const manifest = buildManifest('demo', zip)
  const registry = await startRegistry(manifest, zip)

  try {
    const result = await installCollection({
      slug: 'demo',
      registry: registry.url,
      token: '',
      version: '',
      target: 'codex',
      dryRun: false,
      json: true,
      force: false,
    })

    assert.equal(result.status, 'installed')
    assert.equal(
      await fs.readFile(path.join(workspace, 'codex-home', 'skills', 'alpha', 'cmd'), 'utf8'),
      'echo ordinary',
    )
    const installed = JSON.parse(
      await fs.readFile(path.join(workspace, 'codex-home', 'skills', '.nexgo', 'installed.json'), 'utf8'),
    )
    assert.equal(installed.items.alpha.collection, 'demo')
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('未管理目录冲突会在 preflight 阶段失败', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const restoreEnv = setEnv('CODEX_HOME', path.join(workspace, 'codex-home'))
  const targetDir = path.join(workspace, 'codex-home', 'skills', 'alpha')
  await fs.mkdir(targetDir, { recursive: true })
  await fs.writeFile(path.join(targetDir, 'SKILL.md'), '# unmanaged')
  const zip = makeZip({ 'alpha/SKILL.md': '# alpha' })
  const manifest = buildManifest('demo', zip)
  const registry = await startRegistry(manifest, zip)

  try {
    await assert.rejects(
      () => installCollection({
        slug: 'demo',
        registry: registry.url,
        token: '',
        version: '',
        target: 'codex',
        dryRun: false,
        json: true,
        force: false,
      }),
      /安装前检查失败/,
    )
    assert.equal(await fs.readFile(path.join(targetDir, 'SKILL.md'), 'utf8'), '# unmanaged')
  } finally {
    await registry.close()
    restoreEnv()
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('commit 失败会回滚已写入的目录', async () => {
  const workspace = await fs.mkdtemp(path.join(os.tmpdir(), 'nexgo-cli-'))
  const targetRoot = path.join(workspace, 'skills')
  const oneFiles = [{ path: 'SKILL.md', content: Buffer.from('# one') }]
  const twoFiles = [{ path: 'SKILL.md', content: Buffer.from('# two') }]
  const plan = {
    nexgoRoot: path.join(targetRoot, '.nexgo'),
    installedPath: path.join(targetRoot, '.nexgo', 'installed.json'),
    installed: { items: {} },
    items: [
      {
        name: 'one',
        path: 'one',
        targetPath: path.join(targetRoot, 'one'),
        action: 'create',
        sha256: checksumSkillFiles(oneFiles),
        files: oneFiles,
      },
      {
        name: 'two',
        path: 'two',
        targetPath: path.join(targetRoot, 'two'),
        action: 'create',
        sha256: 'bad',
        files: twoFiles,
      },
    ],
  }

  try {
    await assert.rejects(
      () => commitPlan({
        adapter: { name: 'codex', skillsDir: targetRoot },
        manifest: { slug: 'demo', version: '1.0.0' },
        plan,
      }),
      /校验失败/,
    )
    assert.equal(await exists(path.join(targetRoot, 'one')), false)
    assert.equal(await exists(path.join(targetRoot, 'two')), false)
  } finally {
    await fs.rm(workspace, { recursive: true, force: true })
  }
})

test('target adapter 解析 codex 和 claude-code 目录', () => {
  const workspace = path.join(os.tmpdir(), 'nexgo-adapters')
  const restoreCodex = setEnv('CODEX_HOME', path.join(workspace, 'codex'))
  const restoreClaude = setEnv('CLAUDE_CODE_HOME', path.join(workspace, 'claude'))
  try {
    assert.equal(resolveTargetAdapter('codex').skillsDir, path.join(workspace, 'codex', 'skills'))
    assert.equal(resolveTargetAdapter('claude-code').skillsDir, path.join(workspace, 'claude', 'skills'))
    assert.throws(() => resolveTargetAdapter('unknown'), /不支持的安装目标/)
  } finally {
    restoreCodex()
    restoreClaude()
  }
})

function buildManifest(slug, zip) {
  const parsed = parseCollectionZip(zip)
  return {
    schema_version: 'nexgo.collection.v1',
    slug,
    name: slug,
    version: '1.0.0',
    package_url: '/packages/demo.zip',
    items: parsed.items.map((item) => ({
      name: item.name,
      path: item.path,
      sha256: item.sha256,
      file_count: item.fileCount,
    })),
  }
}

function makeZip(files) {
  const localRecords = []
  const centralRecords = []
  let offset = 0

  for (const [name, value] of Object.entries(files)) {
    const nameBuffer = Buffer.from(name)
    const content = Buffer.isBuffer(value) ? value : Buffer.from(value)
    const localHeader = Buffer.alloc(30)
    localHeader.writeUInt32LE(0x04034b50, 0)
    localHeader.writeUInt16LE(20, 4)
    localHeader.writeUInt16LE(0, 6)
    localHeader.writeUInt16LE(0, 8)
    localHeader.writeUInt32LE(0, 10)
    localHeader.writeUInt32LE(0, 14)
    localHeader.writeUInt32LE(content.length, 18)
    localHeader.writeUInt32LE(content.length, 22)
    localHeader.writeUInt16LE(nameBuffer.length, 26)
    localHeader.writeUInt16LE(0, 28)
    localRecords.push(localHeader, nameBuffer, content)

    const centralHeader = Buffer.alloc(46)
    centralHeader.writeUInt32LE(0x02014b50, 0)
    centralHeader.writeUInt16LE(20, 4)
    centralHeader.writeUInt16LE(20, 6)
    centralHeader.writeUInt16LE(0, 8)
    centralHeader.writeUInt16LE(0, 10)
    centralHeader.writeUInt32LE(0, 12)
    centralHeader.writeUInt32LE(0, 16)
    centralHeader.writeUInt32LE(content.length, 20)
    centralHeader.writeUInt32LE(content.length, 24)
    centralHeader.writeUInt16LE(nameBuffer.length, 28)
    centralHeader.writeUInt16LE(0, 30)
    centralHeader.writeUInt16LE(0, 32)
    centralHeader.writeUInt32LE(0, 34)
    centralHeader.writeUInt32LE(0, 38)
    centralHeader.writeUInt32LE(offset, 42)
    centralRecords.push(centralHeader, nameBuffer)
    offset += localHeader.length + nameBuffer.length + content.length
  }

  const centralDirectory = Buffer.concat(centralRecords)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(0, 4)
  end.writeUInt16LE(0, 6)
  end.writeUInt16LE(Object.keys(files).length, 8)
  end.writeUInt16LE(Object.keys(files).length, 10)
  end.writeUInt32LE(centralDirectory.length, 12)
  end.writeUInt32LE(offset, 16)
  end.writeUInt16LE(0, 20)
  return Buffer.concat([...localRecords, centralDirectory, end])
}

async function startRegistry(manifest, zip) {
  const server = http.createServer((request, response) => {
    if (request.url.startsWith('/api/collections/demo/manifest')) {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify(manifest))
      return
    }
    if (request.url === '/packages/demo.zip') {
      response.writeHead(200, { 'content-type': 'application/zip' })
      response.end(zip)
      return
    }
    response.writeHead(404)
    response.end()
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  return {
    url: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolve) => server.close(resolve)),
  }
}

async function startAuthRegistry(manifest, zip, { expectedToken }) {
  const requests = []
  const server = http.createServer((request, response) => {
    const requestPath = new URL(request.url, 'http://127.0.0.1').pathname
    requests.push({
      path: requestPath,
      authorization: request.headers.authorization,
    })

    const expectedAuthorization = expectedToken ? `Bearer ${expectedToken}` : undefined
    if (request.headers.authorization !== expectedAuthorization) {
      response.writeHead(401, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ detail: 'Unauthorized' }))
      return
    }
    if (requestPath === '/api/collections/demo/manifest') {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify(manifest))
      return
    }
    if (requestPath === '/packages/demo.zip') {
      response.writeHead(200, { 'content-type': 'application/zip' })
      response.end(zip)
      return
    }
    response.writeHead(404)
    response.end()
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  return {
    url: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise((resolve) => server.close(resolve)),
  }
}

function setEnv(name, value) {
  const previous = process.env[name]
  process.env[name] = value
  return () => {
    if (previous === undefined) {
      delete process.env[name]
    } else {
      process.env[name] = previous
    }
  }
}

async function exists(targetPath) {
  try {
    await fs.access(targetPath)
    return true
  } catch {
    return false
  }
}
