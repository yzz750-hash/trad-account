Stage 5: Code Development (编码开发)

G4 提成引擎 (Commission Engine) 已完成：
- 3 个新模型 (Salesperson, OEMContract, CommissionRule)
- 提成计算引擎 (commission.py)
- API 端点 (GET /reports/commission)
- 16 个测试全部通过
- 前端"佣金"tab 已完成

G8 科目余额表 (AccountBalance) 已完成：
- 模型、迁移、compute_period_balances 均就绪
- 结账时自动计算并写入余额表
- 反结账时删除相关余额行
- 回填端点 (POST /system/backfill-balances)
- 报表混合查询：已结账期间读 AccountBalance，未结账期间实时汇总
- 总账优化：已结账月份用 AccountBalance.period_*，仅未结账月份扫描 VoucherEntry
- 新增 2 个测试 (TestAccountBalanceOnClose)

G9 安全审计修复 (10 items) 已完成：
- 1 CRITICAL: 凭证创建借贷平衡逻辑反转
- 2 CRITICAL: 银行导入 float() 改 Decimal()
- 3 CRITICAL: 备份恢复命令注入 (shlex.quote)
- 4 CRITICAL: 备份恢复路径穿越验证
- 5 CRITICAL: .env 弱密码替换为强随机值
- 6 HIGH: AI 端点创建凭证前校验期间状态
- 7 HIGH: 前端科目余额 Number() 累加改 decimal.js
- 8 HIGH: compute_period_balances 上期余额加行锁
- 9 HIGH: ALLOWED_ORIGINS=* 生产拒绝启动
- 10 MEDIUM: post/unpost/batch_review 加 with_for_update()

当前状态：268/268 测试全部通过。

G7 PostgreSQL 迁移验证 已完成：
- Alembic upgrade head 针对 PostgreSQL 成功应用全部 6 个迁移
- WSL2 NAT 网络不稳定导致全量测试套件无法针对 PG 运行（非迁移问题）
- 所有迁移在 SQLite 和 PG 上均正常工作
- 修复 backup_router prefix 回归 (/api/v1/backup → /api/v1/system)
