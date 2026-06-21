from app.database import SessionLocal
from app.models.financial import (
    Account, AccountType, AccountDirection,
    AccountingPeriod, PeriodStatus,
    Currency, ExchangeRate,
    BusinessPartner, PartnerType, Ledger
)

db = SessionLocal()

ledger = Ledger(name="深圳总公司账套", company_name="深圳总公司", base_currency="CNY", start_year=2026, start_month=6)
db.add(ledger)
db.commit()
db.refresh(ledger)

# 1. Seed Accounts
accounts = [
    {"code": "1001", "name": "库存现金", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1002", "name": "银行存款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1122", "name": "应收账款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1123", "name": "预付账款", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1403", "name": "原材料", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1405", "name": "库存商品", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1601", "name": "固定资产", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.DEBIT},
    {"code": "1602", "name": "累计折旧", "account_type": AccountType.ASSET, "balance_direction": AccountDirection.CREDIT},
    {"code": "2001", "name": "短期借款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2202", "name": "应付账款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2203", "name": "预收账款", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2211", "name": "应付职工薪酬", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "2221", "name": "应交税费", "account_type": AccountType.LIABILITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4001", "name": "实收资本", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4103", "name": "本年利润", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "4104", "name": "利润分配", "account_type": AccountType.EQUITY, "balance_direction": AccountDirection.CREDIT},
    {"code": "5001", "name": "生产成本", "account_type": AccountType.COST, "balance_direction": AccountDirection.DEBIT},
    {"code": "6001", "name": "主营业务收入", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6051", "name": "其他业务收入", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.CREDIT},
    {"code": "6401", "name": "主营业务成本", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6402", "name": "其他业务成本", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6403", "name": "税金及附加", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6601", "name": "销售费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6602", "name": "管理费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
    {"code": "6603", "name": "财务费用", "account_type": AccountType.PROFIT_LOSS, "balance_direction": AccountDirection.DEBIT},
]

for acc_data in accounts:
    acc_data["ledger_id"] = ledger.id
    db.add(Account(**acc_data))

# 2. Seed Accounting Period
period = AccountingPeriod(ledger_id=ledger.id, year=2026, month=6, status=PeriodStatus.OPEN)
db.add(period)
db.commit() # commit to get period id

# 3. Seed Currencies & Exchange Rates
cny = Currency(code="CNY", name="人民币", is_base=True)
usd = Currency(code="USD", name="美元", is_base=False)
eur = Currency(code="EUR", name="欧元", is_base=False)
db.add_all([cny, usd, eur])
db.commit()

# Current Rates for 2026-06
db.add_all([
    ExchangeRate(period_id=period.id, currency_id=usd.id, rate=7.2500),
    ExchangeRate(period_id=period.id, currency_id=eur.id, rate=7.8500),
])

# 4. Seed Business Partners
partners = [
    BusinessPartner(ledger_id=ledger.id, code="CUST001", name="Global Trading LLC (USA)", partner_type=PartnerType.CUSTOMER),
    BusinessPartner(ledger_id=ledger.id, code="CUST002", name="Euro Import GmbH (GER)", partner_type=PartnerType.CUSTOMER),
    BusinessPartner(ledger_id=ledger.id, code="VEND001", name="深圳市智造电子有限公司", partner_type=PartnerType.VENDOR),
    BusinessPartner(ledger_id=ledger.id, code="VEND002", name="义乌市小商品批发中心", partner_type=PartnerType.VENDOR),
]
db.add_all(partners)

db.commit()
print("Database initialized successfully with Phase 1 & 2 base data.")
