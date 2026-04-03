# 项目初始化基线

## 1. 项目定位

这是一个 **Skills 库管理系统**，核心目标只有两件事：

1. 管理本地 Skills 库：创建、升级、删除、版本追溯。
2. 聚合外部 `skills.sh`：统一搜索和查看详情，但外部数据只读。

不要把它做成通用 CMS，也不要扩成复杂权限系统。当前系统是 **单管理员后台 + 本地库管理 + 外部库聚合展示**。

## 2. 关键技术框架

### 前端

- `Vue 3`
- `Vue Router`
- `Vite`
- 原生 `fetch`，统一封装在 `frontend/src/services/api.js`

### 后端

- `FastAPI`
- `SQLAlchemy 2`
- `PostgreSQL`
- `Pydantic Settings`
- `PyJWT`
- `markdown-it-py + bleach`

### 部署

- 前后端分离开发
- 生产为 **单镜像承载前端静态资源 + FastAPI**
- `docker-compose` 依赖 `PostgreSQL`

## 3. 核心架构分层

### 后端分层

- `api/`：路由层，只做协议转换、鉴权、参数校验入口
- `services/`：核心业务逻辑
- `models/`：数据库模型
- `schemas/`：接口出入参
- `core/`：配置、JWT、安全能力
- `db/`：引擎、Base、兼容性补丁

原则：

- 业务规则尽量放 `services/`
- 路由层不要堆业务判断
- 数据结构变化先看 `models + schemas + service` 是否同时闭环

### 前端分层

- `views/`：页面级容器
- `components/`：可复用展示组件
- `services/api.js`：唯一 API 访问出口
- `router/`：路由与后台鉴权守卫

原则：

- 页面负责状态编排
- API 调用不要散落到组件内部

## 4. 核心数据模型

### Skill

表示当前生效版本的快照，关键字段：

- `name`：唯一标识，格式固定为小写字母/数字/中划线
- `description_markdown`
- `description_html`
- `contributor`
- `package_url`
- `current_version`
- `deleted_at`

### SkillVersion

表示历史版本快照，用于版本追溯。每次升级都新增一条版本记录，而不是覆盖历史。

结论：

- `Skill` 是“当前态”
- `SkillVersion` 是“历史态”

## 5. 核心业务逻辑

### 公开侧

- 首页同时展示两类数据：
  - 本地库：来自数据库
  - `skills.sh`：来自远程抓取/查询
- 本地库是可控资产，外部库只是聚合展示
- 远程失败不能影响本地库展示

### 后台侧

- 登录后可管理本地 Skill
- 创建 Skill 时必须上传 ZIP
- ZIP 内必须包含非空 `SKILL.md`
- 更新 Skill 时：
  - 可只改描述/贡献者
  - 也可同时上传新 ZIP
  - 每次更新都会生成新版本号和版本历史
- 删除是**软删除**，不是物理删除

### 发布链路

1. 后台上传 ZIP
2. 后端校验 ZIP 合法性
3. 上传到 Nexus Raw 仓库
4. 保存数据库当前版本快照
5. 同步写入 `SkillVersion` 历史记录

## 6. 当前固定约束

这些约束属于系统基线，后续开发不要轻易改：

- Skill 名称格式固定：`^[a-z0-9]+(?:-[a-z0-9]+)*$`
- 版本号是三段式，当前实现为自动递增，最大到 `9.9.9`
- Markdown 必须先转 HTML，再做安全清洗
- 后台认证是 **单管理员 JWT 模式**，不是多用户体系
- 本地 Skill 才允许管理；`skills.sh` 只读
- 删除后前后台都不可再查到该 Skill
- 前端详情主要通过首页 Query 参数驱动，不是复杂多页流转

## 7. 后续开发不要跑偏的方向

### 可以继续演进的点

- 补强后台表单校验与交互体验
- 增加 Nexus 上传失败、远程源异常的可观测性
- 扩展更多只读外部 Skill 源
- 完善测试覆盖，尤其是版本升级和远程聚合场景

### 不建议现在做的点

- 不要引入复杂 RBAC
- 不要把 Skill 内容编辑做成富文本 CMS
- 不要把外部 `skills.sh` 数据落库成本地镜像
- 不要绕开 `services/` 直接在路由层堆业务

## 8. 开发落点建议

后续新增需求时，优先按下面思路落：

1. 先判断需求属于 **本地库管理** 还是 **外部库聚合**
2. 再确认是否会影响 `Skill / SkillVersion` 数据边界
3. 后端先收敛到 `services/`
4. 前端统一走 `services/api.js`
5. 最后补测试，优先覆盖创建、升级、删除、远程失败兜底
