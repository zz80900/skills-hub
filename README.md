# Skills 库管理系统

基于 Vue + FastAPI + PostgreSQL 的 Skills 库管理系统，用于展示 Skill 详情、搜索 Skill，并通过登录工作台上传或升级 Skill ZIP 包到私有 Nexus。

## 功能

- 首页展示 Skills 列表，并在使用教程中提示 Node.js / npx 前置条件
- 支持按 Skill 名称和描述搜索
- Skill 详情页展示 Markdown 描述、安装命令和 ZIP 下载地址
- 采用基础 RBAC0 权限模型，固定角色为管理员和普通用户
- 管理员账号由系统启动时自动种子化，支持后台创建本地用户、分配角色、停启账号和重置密码
- 登录时优先匹配本地用户；本地不存在时可切换到 AD 域 Kerberos + LDAP 认证，并自动建普通用户
- 普通用户登录后仅能查看和操作自己上传的 Skill，管理员可查看全部 Skill 并看到逻辑删除状态
- 工作台支持创建 Skill、上传 ZIP、升级同名 Skill 和逻辑删除
- 工作台支持上传 Skill 集合 ZIP，自动识别根目录一级 Skill 目录并生成 Skill 集合 manifest
- Skill 集合详情提供 `npx nexgo-skills install collection <slug>` 安装命令，CLI 会按目标 Agent 目录批量安装并失败回滚
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
npx nexgo-skills install collection frontend-basic
npx nexgo-skills install collection frontend-basic --target codex
npx nexgo-skills install collection frontend-basic --target claude-code
npx nexgo-skills install collection frontend-basic --dry-run --json
```

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
