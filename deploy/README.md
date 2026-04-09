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

说明：

- Docker 部署只会读取当前目录下的 `deploy/.env`
- `backend/.env` 已被 [.dockerignore](/E:/code_ai/ssc-skills-lib/.dockerignore) 排除，不会打进镜像，也不会被容器内的 FastAPI 自动读取
- 如果你把 AD 配置只写在 `backend/.env`，登录时仍会返回 `AD 认证服务暂不可用`

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
CLI_INSTALL_COMMAND=npm install @xgd/nexgo-skills -g --registry "http://nexus.example.invalid:8081/repository/npm-all"
```

AD 配置最小示例：

```env
AD_ENABLED=true
AD_REALM=XGD.COM
AD_KDC=10.18.8.16
AD_LDAP_URL=ldap://10.18.8.16:389
AD_BASE_DN=OU=新国都集团|OU=支付硬件事业群|OU=技术中心
AD_NETBIOS_DOMAIN=XGD
AD_LDAP_BIND_USERNAME=ssc-skills
AD_LDAP_BIND_PASSWORD=替换成实际密码
# 目录要求 UPN 绑定时再启用
AD_LDAP_BIND_PRINCIPAL=ssc-skills@XGD.COM
```

注意：

- `AD_ENABLED` 必须为 `true`
- `AD_REALM`、`AD_KDC`、`AD_LDAP_URL`、`AD_BASE_DN`、`AD_LDAP_BIND_USERNAME`、`AD_LDAP_BIND_PASSWORD` 任一缺失，后端会直接返回 503
- `AD_DOMAIN_ROOT_DN` 可留空，程序会按 `AD_REALM` 自动推导，例如 `XGD.COM -> DC=xgd,DC=com`
- 修改 `deploy/.env` 后需要重新执行 `docker compose up -d`

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
