"""Seed default chart of accounts for a specific ledger.
Usage: python scripts/seed_accounts.py [ledger_id]
"""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.financial import Account, AccountType, AccountDirection

LEDGER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
db = SessionLocal()

accounts = [
    # 资产类
    {"code": "1001", "name": "库存现金", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1002", "name": "银行存款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1012", "name": "其他货币资金", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1121", "name": "应收票据", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1122", "name": "应收账款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1123", "name": "预付账款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1221", "name": "其他应收款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1231", "name": "坏账准备", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1401", "name": "材料采购", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1402", "name": "在途物资", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1403", "name": "原材料", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1404", "name": "材料成本差异", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1405", "name": "库存商品", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1406", "name": "发出商品", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1407", "name": "商品进销差价", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1408", "name": "委托加工物资", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1411", "name": "周转材料", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1471", "name": "存货跌价准备", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1501", "name": "长期股权投资", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1502", "name": "长期股权投资减值准备", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1511", "name": "长期应收款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1601", "name": "固定资产", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1602", "name": "累计折旧", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1603", "name": "固定资产减值准备", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1604", "name": "在建工程", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1605", "name": "工程物资", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1606", "name": "固定资产清理", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1701", "name": "无形资产", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1702", "name": "累计摊销", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1703", "name": "无形资产减值准备", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "1801", "name": "长期待摊费用", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1901", "name": "待处理财产损溢", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    # 负债类
    {"code": "2001", "name": "短期借款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2101", "name": "交易性金融负债", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2201", "name": "应付票据", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2202", "name": "应付账款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2203", "name": "预收账款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2211", "name": "应付职工薪酬", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2221", "name": "应交税费", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2231", "name": "应付利息", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2232", "name": "应付股利", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2241", "name": "其他应付款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2401", "name": "递延收益", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2501", "name": "长期借款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2502", "name": "应付债券", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2701", "name": "长期应付款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2801", "name": "预计负债", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    # 所有者权益类
    {"code": "4001", "name": "实收资本", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4002", "name": "资本公积", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4101", "name": "盈余公积", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4103", "name": "本年利润", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4104", "name": "利润分配", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    # 成本类
    {"code": "5001", "name": "生产成本", "account_type": AccountType.COST, "balance_direction": AccountDirection.DEBIT},
    {"code": "5101", "name": "制造费用", "account_type": AccountType.COST, "balance_direction": AccountDirection.DEBIT},
    {"code": "5201", "name": "劳务成本", "account_type": AccountType.COST, "balance_direction": AccountDirection.DEBIT},
    {"code": "5301", "name": "研发支出", "account_type": AccountType.COST, "balance_direction": AccountDirection.DEBIT},
    # 损益类
    {"code": "6001", "name": "主营业务收入", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6051", "name": "其他业务收入", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6101", "name": "公允价值变动损益", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6111", "name": "投资收益", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6301", "name": "营业外收入", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6401", "name": "主营业务成本", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6402", "name": "其他业务成本", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6403", "name": "税金及附加", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6601", "name": "销售费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6602", "name": "管理费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6603", "name": "财务费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6701", "name": "资产减值损失", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6711", "name": "营业外支出", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6801", "name": "所得税费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6901", "name": "以前年度损益调整", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
]

added = 0
for acc_data in accounts:
    existing = db.query(Account).filter(Account.code == acc_data["code"], Account.ledger_id == LEDGER_ID).first()
    if not existing:
        db.add(Account(**acc_data, ledger_id=LEDGER_ID))
        added += 1

db.commit()
print(f"Seeded {added} accounts for ledger_id={LEDGER_ID} (existing unchanged).")
