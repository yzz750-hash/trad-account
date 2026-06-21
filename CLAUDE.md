# Trad Account — AI 开发协作指南

## 项目概述

智能会计/财务系统（trad account），多账套 SaaS，支持凭证管理、固定资产折旧、外币重估、税务计算、OEM 合同损益、销售提成等。

**技术栈：**
- 后端：Python 3.14, FastAPI, SQLAlchemy ORM, Alembic, Pydantic
- 前端：Next.js 16.2, TypeScript 5, TailwindCSS 4
- 数据库：SQLite（开发/测试），PostgreSQL（生产）
- 测试：pytest + TestClient（后端），Playwright（前端 e2e）

**项目路径：** `d:\antigravity ide text\trad account\`
- 后端：`backend\`
- 前端：`frontend\`
- 后端虚拟环境：`backend\venv\Scripts\python.exe`
- 前端依赖：`frontend\node_modules\`

---

## 10 阶段 AI 编程工作流

进行任何开发任务时，自动判断当前所处阶段并遵循对应流程。**每个阶段完成后更新状态到 `STAGE.md`。**

### 阶段自动检测

| 信号 | 判定阶段 |
|------|---------|
| 用户提出新功能想法、需求模糊 | ① 立项评估 |
| 需求明确但无技术方案 | ② 需求分析 → ③ 原型设计 → ④ 技术方案 |
| 有明确技术方案和实现计划 | ⑤ 编码开发 |
| 代码已写、有测试失败 | ⑥ 测试调试 |
| 前后端都已完成、需要联调 | ⑦ 联调验收 |
| 功能完成、准备合并 | ⑧ 代码审查 |
| 审查通过、准备部署 | ⑨ 发布上线 |
| 上线后回顾 | ⑩ 复盘沉淀 |

### ① 立项评估
- 判断需求是否属于本项目范围（财务会计系统）
- 评估可行性和工作量
- 如果需求不在范围内，建议拆分为独立项目
- **输出：** 可行性结论 + 粗略工作量估算

### ② 需求分析
- 将用户故事拆解为功能点
- 识别边界条件和异常情况
- 检查与现有功能的冲突
- **输出：** 功能清单 + 验收标准

### ③ 原型设计
- 设计 UI 交互流程（前端任务）
- 设计 API 契约（后端任务）
- 设计数据模型变更
- **输出：** 交互原型描述 + API 草图 + 数据模型

### ④ 技术方案
- 确定具体实现方案、文件变更清单
- 评估对现有功能的影响
- 使用 EnterPlanMode 编写详细实施计划
- **输出：** 经用户确认的实施计划

### ⑤ 编码开发
- 严格按计划实施，每个 Task 2-5 分钟完成
- 遵循 TDD：先写测试 → 测试失败 → 写实现 → 测试通过 → 提交
- 后端测试：`cd backend && .\venv\Scripts\python.exe -m pytest tests/test_xxx.py -v`
- 前端类型检查：`cd frontend && npx tsc --noEmit`
- **每条提交必须：** 描述清晰 + 通过全部相关测试

### ⑥ 测试调试
- 运行完整测试套件：`cd backend && .\venv\Scripts\python.exe -m pytest tests/ -v`
- 修复失败测试，确保零回归
- 手动验证 golden path 和 edge cases
- **输出：** 全部测试通过 + 手动验证记录

### ⑦ 联调验收
- 启动后端（端口 8004+）：`cd backend && .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload`
- 启动前端（端口 3001）：`cd frontend && npx next dev --port 3001`
- 端到端验证完整用户流程
- 检查浏览器控制台无错误
- **输出：** 联调通过确认

### ⑧ 代码审查
- 检查安全漏洞（OWASP top 10）
- 检查 SQL 注入、XSS、权限绕过
- 验证多账套隔离（X-Ledger-Id）
- 检查敏感数据加密
- **输出：** 审查结论 + 问题清单（如有）

### ⑨ 发布上线
- 运行 Alembic migration：`cd backend && .\venv\Scripts\python.exe -m alembic upgrade head`
- 确认 PostgreSQL 兼容性
- 更新 CHANGELOG
- 打 tag
- **输出：** 部署确认

### ⑩ 复盘沉淀
- 总结实现过程中的关键决策
- 记录踩坑和解决方案
- 更新 CLAUDE.md 和 memory
- **输出：** 复盘记录

---

## 开发约定

### 绝对路径
所有命令使用绝对路径，不依赖 `cd`：
- Python：`d:\antigravity ide text\trad account\backend\venv\Scripts\python.exe`
- Alembic：通过 Python 模块调用 `-m alembic`
- 工作目录设为 `d:\antigravity ide text\trad account\backend`

### 测试规范
- 每个新功能必须写 pytest 测试
- 测试文件放在 `backend\tests\`，命名 `test_<feature>.py`
- 测试类继承模式，使用 `db` 和 `ledger` fixtures（见 conftest.py）
- 环境变量：`JWT_SECRET_KEY="test-secret-key-for-testing-only" SKIP_DOCKER_TESTS="1"`

### 多账套隔离
- 所有 API 通过 `X-Ledger-Id` header 隔离数据
- 数据库查询必须过滤 `ledger_id`
- 测试中验证跨账套隔离

### 安全要求
- 密码使用 bcrypt 哈希
- API key 使用 AES 加密存储（EncryptedString）
- JWT token 包含 token_version 用于登出失效
- 审计日志记录所有 API 请求

### 端口约定
- 避免 8000-8003（Windows zombie 进程占用）
- 后端开发：8004+
- 前端开发：3001（避免与 Codex CLI 冲突）

### 前端约定
- Client Components only（Next.js App Router）
- 使用 apiFetch() 封装（`frontend\src\lib\api.ts`）
- Tab 切换模式参考 reports/page.tsx

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `backend\app\models\financial.py` | 全部 SQLAlchemy 模型 |
| `backend\app\routers\reports.py` | 报表 API 端点 |
| `backend\app\commission.py` | 提成计算引擎 |
| `backend\app\auth.py` | JWT 认证和权限管理 |
| `backend\app\encryption.py` | AES 加密（EncryptedString） |
| `backend\alembic\versions\` | 数据库迁移链 |
| `backend\tests\conftest.py` | pytest fixtures |
| `frontend\src\app\reports\page.tsx` | 报表页面（含提成 tab） |
| `frontend\src\lib\api.ts` | 前端 API 封装 |

## 当前项目状态

参考 auto-memory 中的最新 `project-state-*.md` 文件获取最新状态。
STAGE.md 记录当前开发阶段。

