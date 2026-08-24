# Skills 库管理系统

基于 Vue + FastAPI + PostgreSQL 的 Skills 库管理系统，用于展示 Skill 详情、搜索 Skill，并通过登录工作台上传或升级 Skill ZIP 包到私有 Nexus。

## 功能

- 首页分别展示本地 Skills 与只读的 skills.sh 外部目录，并为本地安装提示 Node.js / npx 前置条件
- 支持按 Skill 名称和描述搜索
- 本地 Skill 详情展示 Markdown 描述、安装命令和 ZIP 下载地址；skills.sh 详情提供官方页面安装入口
- 采用基础 RBAC0 权限模型，固定角色为管理员和普通用户
- 管理员账号由系统启动时自动种子化，支持后台创建本地用户、分配角色、停启账号和重置密码
- 登录时优先匹配本地用户；本地不存在时可切换到 AD 域 Kerberos + LDAP 认证，并自动建普通用户
- 普通用户登录后仅能查看和操作自己上传的 Skill，管理员可查看全部 Skill 并看到逻辑删除状态
- 工作台支持创建 Skill、上传 ZIP、升级同名 Skill 和逻辑删除
- 工作台支持上传 Skill 集合 ZIP，自动识别根目录一级 Skill 目录并生成 Skill 集合 manifest
- Skill 集合详情提供 `npx nexgo-skills@latest install collection <slug>` 安装命令，CLI 会按目标 Agent 目录批量安装并失败回滚
- 上传 Skill ZIP 时校验根目录必须包含非空 `SKILL.md`，可选 `cmd` 只作为普通包内容保存
- ZIP 上传到私有 Nexus `raw-repo/skills/{name}.zip`

## Skill ZIP 约束

工作台上传 Skill ZIP 时，压缩包根目录建议保持如下结构：

```text
your-skill.zip
|- SKILL.md
\- cmd        # 可选，普通文本文件
```

- 根目录必须存在非空 `SKILL.md`
- `cmd` 可以存在，但服务端和 CLI 都不会解析、校验或执行它
- 安装行为来自 `nexgo-skills` CLI 和 target adapter，不来自包内脚本

## Skill 集合 ZIP 约束

工作台上传 Skill 集合 ZIP 时，压缩包根目录下的每个一级目录都会被识别为一个 Skill：

```text
frontend-basic.zip
|- frontend-design/
|  |- SKILL.md
|  \- references/
|- code-review/
|  \- SKILL.md
\- commit-helper/
   \- SKILL.md
```

- 根目录只能包含 Skill 目录，不能包含 `README.md`、`collection.json` 或其他普通文件
- 每个 Skill 目录必须直接包含非空 `SKILL.md`
- 不需要 `skills/`、`codex/`、`claude-code/` 等包裹目录
- 服务端会根据 ZIP 内容生成内部 manifest 和每个 Skill 的规范化 checksum
- Skill 集合版本号由系统自动管理：创建时为 `1.0.0`，上传新 ZIP 时按单个 Skill 的规则自动递增
- Skill 集合包保存到 Nexus 专属路径：`raw-repo/skills/collections/{slug}/{version}.zip`

## CLI Skill 集合安装

默认安装命令：

```powershell
npx nexgo-skills@latest install collection frontend-basic
npx nexgo-skills@latest install collection frontend-basic --agent codex
npx nexgo-skills@latest install collection frontend-basic --agent claude
npx nexgo-skills@latest install collection frontend-basic --api-key ns-...
npx nexgo-skills@latest install collection frontend-basic --dry-run --json
```

集合安装只接受 NEXGO API Key。CLI 会优先读取 `NEXGO_SKILLS_API_KEY`，未配置时再读取 `--api-key` 参数。请访问 `https://skills.nexgoglobal.com` 登录后获取 API Key。

CLI 会先获取 Skill 集合 manifest，再下载 ZIP 并校验每个 Skill checksum。安装写入目标 Agent 的 Skill 目录；若任意步骤失败，会删除本次新增目录并恢复被覆盖目录。

## 目录

```text
backend/   FastAPI 服务
frontend/  Vue 前端
```

## 启动后端

1. 创建虚拟环境并安装依赖：

```powershell
cd "E:/code_ai/nexgo-skills-lib/backend"
python -m venv ".venv"
".venv/Scripts/pip" install -r "requirements.txt"
```

2. 配置环境变量：

```powershell
Copy-Item ".env.example" ".env"
```

3. 启动服务：

```powershell
".venv/Scripts/uvicorn" "app.main:app" --reload --host 0.0.0.0 --port 8000
```

## OpenAPI 与 MCP

后端同时保留两类入口：

- REST/OpenAPI：`/api/*`，Swagger UI 为 `/docs`，规范文件为 `/openapi.json`
- MCP：`/mcp`，使用 Streamable HTTP；该入口不会出现在 OpenAPI 文档中

MCP 客户端必须支持远程 Streamable HTTP，并允许为每个 HTTP 请求配置静态 `Authorization` Header。只支持 stdio、旧 SSE，或不能设置自定义 Header 的客户端不能直接连接该入口。

匿名连接可以浏览公开 Skill/集合元数据。需要查看当前账号可管理资源、预览压缩包或执行创建、更新、删除时，先在登录后的账号设置中创建 API Key，再按下面的形式配置客户端：

```json
{
  "url": "http://localhost:8000/mcp",
  "headers": {
    "Authorization": "Bearer ns-替换为当前API-Key"
  }
}
```

- MCP 只接受当前有效的 `ns-` API Key，不接受登录 JWT
- API Key 明文只在创建或轮转成功时返回一次；每个用户只保留一个 Key，轮转后旧 Key 立即失效
- 未携带 `Authorization` 时按匿名处理；显式提供畸形、无效、已轮转或停用账号的 Key 时返回 HTTP `401`
- 不会从 URL 查询参数、Cookie、工具参数或 `X-API-Key` 等自定义 Header 读取 Key

MCP 工具目录：

- 公开读取：`nexgo_skills_search`、`nexgo_skill_get`、`nexgo_skill_download`、`nexgo_collections_list`、`nexgo_collection_get`、`nexgo_collection_manifest_get`、`nexgo_collection_download`
- 管理读取：`nexgo_managed_skills_list`、`nexgo_managed_skill_get`、`nexgo_managed_collections_list`、`nexgo_managed_collection_get`
- Skill 变更：`nexgo_skill_create`、`nexgo_skill_update`、`nexgo_skill_delete`
- 集合变更：`nexgo_collection_preview`、`nexgo_collection_create`、`nexgo_collection_update`、`nexgo_collection_delete`

下载采用两步流程：先调用 MCP 下载工具取得应用内 `download_path`、文件名、版本和 `requires_api_key`，再对该 REST 路径发起 GET。`requires_api_key=true` 时，下载请求必须再次携带同一个当前有效的 API Key；公开包可以匿名下载。MCP 结果和下载 URL 都不会包含 API Key、Nexus 凭证或 Nexus 原始地址。

MCP 创建、更新和集合预览使用严格 Base64 的 `package_base64`。默认解码后包上限为 20 MiB，MCP HTTP 请求体上限为 32 MiB；更大的包应改用现有 OpenAPI multipart 工作台接口。相关配置如下：

```dotenv
MCP_ENABLED=true
MCP_ALLOWED_HOSTS=localhost,localhost:*,127.0.0.1,127.0.0.1:*
MCP_ALLOWED_ORIGINS=http://localhost:*,http://127.0.0.1:*
MCP_MAX_PACKAGE_BYTES=20971520
MCP_MAX_REQUEST_BODY_BYTES=33554432
```

生产环境必须把 Host/Origin allowlist 改为实际域名和来源；临时回滚可设置 `MCP_ENABLED=false`，不会影响 REST、前端、CLI 或已创建的 API Key。

## 启动前端

```powershell
cd "E:/code_ai/nexgo-skills-lib/frontend"
npm install
npm run dev
```

默认开发地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

## 一键启动本地开发环境

仓库根目录提供了统一脚本 [dev.ps1](E:/code_ai/nexgo-skills-lib/dev.ps1)，默认行为是：

- 后端使用仓库内 `backend/local-dev.db` 作为 SQLite 本地开发库
- 前端启动 Vite 开发服务器
- 自动记录前后端根进程 PID，方便后续关闭和查看状态

常用命令：

```powershell
cd "E:/code_ai/nexgo-skills-lib"
./dev.ps1 start
./dev.ps1 status
./dev.ps1 stop
./dev.ps1 restart
```

如果你要改回 `.env` 中的数据库配置，例如本机 PostgreSQL：

```powershell
./dev.ps1 start -UseEnvDatabase
```

脚本启动后默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

日志文件位置：

- `backend/latest_logs/dev-backend.log`
- `backend/latest_logs/dev-backend.err.log`
- `frontend/latest_logs/dev-frontend.log`
- `frontend/latest_logs/dev-frontend.err.log`

## Docker 部署

单镜像同时承载前端和后端，编排文件位于 [deploy/docker-compose.yml](E:/code_ai/nexgo-skills-lib/deploy/docker-compose.yml)。

```powershell
cd "E:/code_ai/nexgo-skills-lib/deploy"
docker compose up -d --build
```

详细说明见 [deploy/README.md](E:/code_ai/nexgo-skills-lib/deploy/README.md)。

## 初始管理员账号

- 用户名：`admin`
- 密码：`admin`

系统会在首次启动时自动创建该管理员账号，建议在生产环境通过环境变量覆盖初始账号密码并及时修改。

## AD 域集成

- 开启 `AD_ENABLED=true` 后，后端会先查本地用户表；若用户名不存在，再走 AD 域认证
- AD 用户使用 Kerberos 校验账号密码，LDAP 仅使用服务账号查询姓名与 principal
- AD 用户首次登录会自动在系统内创建 `USER` 普通用户，并记录用户来源、展示姓名、外部 principal
- AD 用户后续仍走域控认证，不支持后台本地重置密码
- 详细认证约束见 [docs/python-ad.md](E:/code_ai/nexgo-skills-lib/docs/python-ad.md)
