# Skills 库管理系统

基于 Vue + FastAPI + PostgreSQL 的 Skills 库管理系统，用于展示 Skill 详情、搜索 Skill，并通过管理后台上传或升级 Skill ZIP 包到私有 Nexus。

## 功能

- 首页展示 CLI 安装提示和 Skills 列表
- 支持按 Skill 名称和描述搜索
- Skill 详情页展示 Markdown 描述、安装命令和 ZIP 下载地址
- 固定管理员 `admin/admin` 登录后台
- 后台支持创建 Skill、上传 ZIP、升级同名 Skill
- 上传时校验 ZIP 必须包含非空 `SKILL.md`
- ZIP 上传到私有 Nexus `raw-repo/skills/{name}.zip`

## 目录

```text
backend/   FastAPI 服务
frontend/  Vue 前端
```

## 启动后端

1. 创建虚拟环境并安装依赖：

```powershell
cd "E:/code_ai/ssc-skills-lib/backend"
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
cd "E:/code_ai/ssc-skills-lib/frontend"
npm install
npm run dev
```

默认开发地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

## Docker 部署

单镜像同时承载前端和后端，编排文件位于 [deploy/docker-compose.yml](E:/code_ai/ssc-skills-lib/deploy/docker-compose.yml)。

```powershell
cd "E:/code_ai/ssc-skills-lib/deploy"
docker compose up -d --build
```

详细说明见 [deploy/README.md](E:/code_ai/ssc-skills-lib/deploy/README.md)。

## 默认账号

- 用户名：`admin`
- 密码：`admin`

建议在生产环境通过环境变量覆盖。
