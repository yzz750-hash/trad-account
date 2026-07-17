# Trad Account Frontend

外贸智能财务系统前端 — Next.js 16.2 App Router.

## 开发

```bash
cp .env.local.example .env.local   # 配置后端地址
npm install
npm run dev                        # http://localhost:3001
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NEXT_PUBLIC_API_URL` | 后端 API 地址 | `http://localhost:8004` |

## E2E 测试

```bash
npx playwright test
```

## 项目结构

```
src/
  app/                  # App Router 页面
    login/              # 登录页
    voucher/            # 凭证管理
    reports/            # 报表（BS/IS/CF/GL/SL）
    settings/           # 系统设置
    period-end/         # 期末结账
  components/           # 共享组件
  lib/                  # API 封装、类型定义
  context/              # React Context (LedgerContext)
e2e/                    # Playwright E2E 测试
```
