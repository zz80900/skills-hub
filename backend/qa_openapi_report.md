# OpenAPI 测试报告

## 结论

- 测试时间：2026-08-24
- 服务地址：`http://127.0.0.1:8000`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI 规范：`http://127.0.0.1:8000/openapi.json`
- 默认管理员：`admin / admin`
- 指定 Skill 包：`C:\Users\xiejincheng\.codex\skills\auto-comment\auto-comment.zip`
- OpenAPI 操作覆盖：`22/22`
- 接口调用结果：`37/37` 通过，`0` 失败
- 测试资源：已调用删除接口做逻辑删除清理

## 覆盖接口

| 方法 | 路径 | 结果 |
| --- | --- | --- |
| GET | `/api/local-library` | 200 通过 |
| GET | `/api/skills/local` | 200 通过 |
| GET | `/api/collections` | 200 通过 |
| GET | `/api/skills` | 200 通过 |
| GET | `/api/skills/skills_sh` | 200 通过 |
| POST | `/api/workspace/skills` | 201 通过 |
| GET | `/api/workspace/skills` | 200 通过 |
| GET | `/api/workspace/skills/{name}` | 200 通过 |
| PUT | `/api/workspace/skills/{name}` | 200 通过 |
| GET | `/api/skills/{source}/{slug}` | 200 通过 |
| GET | `/api/skills/local/{slug}/versions/{version}` | 200 通过 |
| GET | `/api/skills/local/{slug}/package` | 200 通过，下载字节与上传包一致 |
| POST | `/api/workspace/collections/preview` | 200 通过 |
| POST | `/api/workspace/collections` | 201 通过 |
| GET | `/api/workspace/collections` | 200 通过 |
| GET | `/api/workspace/collections/{slug}` | 200 通过 |
| PUT | `/api/workspace/collections/{slug}` | 200 通过 |
| GET | `/api/collections/{slug}` | 200 通过 |
| GET | `/api/collections/{slug}/manifest` | 200 通过 |
| GET | `/api/collections/{slug}/package` | 200 通过，下载字节与上传包一致 |
| DELETE | `/api/workspace/collections/{slug}` | 200 通过，清理 |
| DELETE | `/api/workspace/skills/{name}` | 200 通过，清理 |

## 前置与页面验证

- `POST /api/auth/login`：默认管理员登录通过。
- `GET /api/auth/me`：当前用户校验通过。
- API Key 查询、创建/已存在处理、轮转均通过；已有 Key 时创建接口返回预期 `409`，轮转返回 `200` 并返回新 Key。
- Swagger UI 页面正常加载，分组和操作数量与 `openapi.json` 一致。
- 后台 API Key 页面只显示 `OpenAPI / REST`，未发现 MCP 文案或 MCP 配置入口。
- 浏览器控制台无错误，截图证据：`qa-openapi-api-key.png`。

## 环境说明

- 项目虚拟环境中的 `mcp==2.0.0` 可正常启动后端。
- 全局 Python 环境为 `mcp==1.26.0`，缺少项目代码依赖的 `MCPServer` 导出；使用项目 `.venv` 后恢复正常。
- 为隔离上传和下载，测试进程使用本机 `127.0.0.1:18081` 的 Nexus 兼容存储桩，没有把测试包发送到 `.env` 中的真实 Nexus 地址。
- 当前开发环境保持运行：前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8000`。

## 可复现文件

- 测试脚本：[qa_openapi_test.py](D:/code_ai/nexgo-skills/nexgo-skills-lib/backend/qa_openapi_test.py)
- 机器可读结果：[qa_openapi_report.json](D:/code_ai/nexgo-skills/nexgo-skills-lib/backend/qa_openapi_report.json)
