# Skills 库管理系统

基于 Vue + FastAPI + PostgreSQL 的 Skills 库管理系统，用于展示 Skill 详情、搜索 Skill，并通过登录工作台上传或升级 Skill ZIP 包到私有 Nexus。

## 功能

- 首页展示 CLI 安装提示和 Skills 列表
- 支持按 Skill 名称和描述搜索
- Skill 详情页展示 Markdown 描述、安装命令和 ZIP 下载地址
- 采用基础 RBAC0 权限模型，固定角色为管理员和普通用户
- 管理员账号由系统启动时自动种子化，支持后台创建本地用户、分配角色、停启账号和重置密码
- 登录时优先匹配本地用户；本地不存在时可切换到 AD 域 Kerberos + LDAP 认证，并自动建普通用户
- 普通用户登录后仅能查看和操作自己上传的 Skill，管理员可查看全部 Skill 并看到逻辑删除状态
- 工作台支持创建 Skill、上传 ZIP、升级同名 Skill 和逻辑删除
- 上传时校验 ZIP 根目录必须包含非空 `SKILL.md`，可选 `cmd` 只能包含单条以 `npm install` 开头的命令
- ZIP 上传到私有 Nexus `raw-repo/skills/{name}.zip`

## Skill ZIP 约束

工作台上传 Skill ZIP 时，压缩包根目录建议保持如下结构：

```text
your-skill.zip
|- SKILL.md
\- cmd        # 可选，仅当需要额外安装 CLI
```

- 根目录必须存在非空 `SKILL.md`
- 如需额外安装 CLI，可在根目录提供一个名为 `cmd` 的文件
- `cmd` 只能包含一条以 `npm install` 开头的命令
- `cmd` 不能包含其他命令、命令拼接或多行脚本

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
