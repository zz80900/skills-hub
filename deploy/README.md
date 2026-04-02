# Docker 部署

## 结构

- `Dockerfile`：构建单镜像，内含前端静态资源和 FastAPI 后端
- `deploy/docker-compose.yml`：直接拉取 `ghcr.io/zz80900/skills-hub` 镜像并启动应用与 PostgreSQL
- `deploy/docker/entrypoint.sh`：容器启动脚本
- `deploy/.env.example`：独立运行 `docker compose` 的环境变量示例

## 准备环境变量

在 `deploy` 目录下基于示例文件创建 `.env`：

```powershell
cd "E:/code_ai/ssc-skills-lib/deploy"
cp ".env.example" ".env"
```

关键配置示例：

```env
APP_IMAGE_TAG=latest
POSTGRES_DB=skills_lib
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/skills_lib
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
JWT_SECRET=replace-with-a-long-secret
JWT_EXPIRE_MINUTES=720
NEXUS_RAW_BASE_URL=http://nexus.example.invalid:8081/repository/raw-repo/skills
NEXUS_USERNAME=your-nexus-username
NEXUS_PASSWORD=your-nexus-password
CORS_ORIGINS=http://localhost:8000
CLI_INSTALL_COMMAND=npm install @xgd/ssc-skills -g --registry "http://nexus.example.invalid:8081/repository/npm-all"
```

## 启动

```powershell
cd "E:/code_ai/ssc-skills-lib/deploy"
docker compose pull
docker compose up -d
```

如果之前已经用旧配置创建过容器，先清理再启动：

```powershell
cd "E:/code_ai/ssc-skills-lib/deploy"
docker compose down -v
docker compose pull
docker compose up -d
```

## 访问

- 应用首页：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`
- PostgreSQL：`localhost:5432`

## 停止

```powershell
cd "E:/code_ai/ssc-skills-lib/deploy"
docker compose down
```
