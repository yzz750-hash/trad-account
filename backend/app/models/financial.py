from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Date,
    ForeignKey,
    Text,
    Boolean,
    JSON,
    Enum,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base
from app.encryption import EncryptedString


class PeriodStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PartnerType(enum.Enum):
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    BOTH = "BOTH"


class AccountDirection(enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    COST = "COST"
    PROFIT_LOSS = "PROFIT_LOSS"


class UserRole(enum.Enum):
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    AUDITOR = "auditor"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.ACCOUNTANT)
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=0, server_default='0', nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, default=0, server_default='0', nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Ledger(Base):
    __tablename__ = "ledgers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    base_currency = Column(String(10), default="CNY")
    start_year = Column(Integer, nullable=False)
    start_month = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    llm_provider = Column(String(50), default="deepseek")
    llm_api_key = Column(EncryptedString(512), nullable=True)
    llm_base_url = Column(String(255), nullable=True)
    llm_model_name = Column(String(100), default="deepseek-chat")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    code = Column(String(50), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    account_type = Column(Enum(AccountType), nullable=False)
    balance_direction = Column(Enum(AccountDirection), nullable=False)

    opening_balance = Column(Numeric(15, 2), default=0.00)
    is_active = Column(Boolean, default=True)

    children = relationship("Account", backref="parent", remote_side=[id])

    __table_args__ = (
        UniqueConstraint("ledger_id", "code", name="uq_account_ledger_code"),
    )


class VoucherStatus(enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    POSTED = "POSTED"


class Voucher(Base):
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    voucher_number = Column(String(50), index=True, nullable=False)
    voucher_date = Column(Date, nullable=False, index=True)
    attachments_count = Column(Integer, default=0)
    status = Column(Enum(VoucherStatus), default=VoucherStatus.DRAFT)

    source_type = Column(String(50), nullable=True)
    contract_number = Column(String(100), nullable=True)

    entries = relationship("VoucherEntry", back_populates="voucher", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ledger_id", "voucher_number", name="uq_voucher_ledger_number"),
    )


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"

    id = Column(Integer, primary_key=True, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    partner_id = Column(Integer, ForeignKey("business_partners.id"), nullable=True)

    summary = Column(String(255), nullable=False)
    direction = Column(Enum(AccountDirection), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)

    currency_code = Column(String(10), default="CNY")
    original_amount = Column(Numeric(15, 2), nullable=True)
    exchange_rate = Column(Numeric(10, 4), default=1.0000)

    vat_rate = Column(Numeric(5, 4), nullable=True)  # e.g. 0.13 for 13% VAT
    vat_amount = Column(Numeric(15, 2), nullable=True)  # VAT portion of this entry

    voucher = relationship("Voucher", back_populates="entries")
    account = relationship("Account")


class OriginalDocument(Base):
    __tablename__ = "original_documents"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False)
    file_path = Column(String(500), nullable=False)

    extracted_data = Column(JSON, nullable=True)
    is_reconciled = Column(Boolean, default=False)
    related_voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=True)


class FixedAsset(Base):
    __tablename__ = "fixed_assets"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    asset_code = Column(String(50), index=True, nullable=False)
    asset_name = Column(String(255), nullable=False)

    purchase_date = Column(Date, nullable=False)
    original_value = Column(Numeric(15, 2), nullable=False)
    salvage_value_rate = Column(Numeric(5, 4), default=0.0500)
    expected_useful_months = Column(Integer, nullable=False)

    accumulated_depreciation = Column(Numeric(15, 2), default=0.00)
    is_active = Column(Boolean, default=True)


class AccountingPeriod(Base):
    __tablename__ = "accounting_periods"
    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    status = Column(Enum(PeriodStatus), default=PeriodStatus.OPEN)

    __table_args__ = (
        UniqueConstraint("ledger_id", "year", "month", name="uq_accounting_period_ledger_year_month"),
    )


class Currency(Base):
    __tablename__ = "currencies"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    name = Column(String(50), nullable=False)
    is_base = Column(Boolean, default=False)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("accounting_periods.id"), nullable=False, index=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    rate = Column(Numeric(12, 8), nullable=False)


class BusinessPartner(Base):
    __tablename__ = "business_partners"
    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    code = Column(String(50), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    partner_type = Column(Enum(PartnerType), nullable=False)
    is_active = Column(Boolean, default=True)


class OpenItemType(enum.Enum):
    INVOICE = "INVOICE"
    BANK_TXN = "BANK_TXN"


class OpenItemStatus(enum.Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLEARED = "CLEARED"


class OpenItem(Base):
    __tablename__ = "open_items"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    item_type = Column(Enum(OpenItemType), nullable=False)
    source_doc_id = Column(Integer, ForeignKey("original_documents.id"), nullable=True)
    txn_index = Column(Integer, nullable=True)

    date = Column(Date, nullable=False)
    counterpart_name = Column(String(255), nullable=True)
    remarks = Column(String(255), nullable=True)

    amount = Column(Numeric(15, 2), nullable=False)
    unreconciled_amount = Column(Numeric(15, 2), nullable=False)

    status = Column(Enum(OpenItemStatus), default=OpenItemStatus.OPEN)


class VoucherNumberCounter(Base):
    __tablename__ = "voucher_number_counters"
    __table_args__ = (
        UniqueConstraint("ledger_id", "prefix", name="uq_voucher_number_counter_ledger_prefix"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    prefix = Column(String(20), nullable=False)
    current_number = Column(Integer, nullable=False, default=0)


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_records"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    reconciled_date = Column(Date, nullable=False)

    invoice_item_id = Column(Integer, ForeignKey("open_items.id"), nullable=False, index=True)
    statement_item_id = Column(Integer, ForeignKey("open_items.id"), nullable=False, index=True)

    matched_amount = Column(Numeric(15, 2), nullable=False)
    discrepancy_amount = Column(Numeric(15, 2), default=0.00)
    discrepancy_type = Column(String(50), nullable=True)

    clearing_voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=True)


class ClosingOperation(Base):
    """Idempotency tracking for period-end closing operations."""
    __tablename__ = "closing_operations"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    operation_type = Column(String(30), nullable=False)  # "depreciate", "profit_loss", "fx_revaluation"
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=True)
    result_message = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ledger_id", "operation_type", "year", "month", name="uq_closing_operation_period"),
    )


class TaxRate(Base):
    """Configurable tax rates for VAT and export rebate calculation."""
    __tablename__ = "tax_rates"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    tax_type = Column(String(30), nullable=False)  # "vat_input", "vat_output", "export_rebate"
    rate = Column(Numeric(5, 4), nullable=False)  # e.g. 0.1300 for 13%
    description = Column(String(100), nullable=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)  # NULL = currently effective
    is_active = Column(Boolean, default=True)


class VATRecord(Base):
    """Tracks VAT amounts per voucher for tax reporting / 纳税申报."""
    __tablename__ = "vat_records"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=False)
    voucher_date = Column(Date, nullable=False, index=True)

    vat_type = Column(String(20), nullable=False)  # "input" (进项) or "output" (销项)
    invoice_code = Column(String(50), nullable=True)  # 发票代码
    invoice_number = Column(String(50), nullable=True)  # 发票号码
    counterpart_name = Column(String(255), nullable=True)

    taxable_amount = Column(Numeric(15, 2), nullable=False, default=0.00)  # 不含税金额
    vat_rate = Column(Numeric(5, 4), nullable=False, default=0.00)  # 税率
    vat_amount = Column(Numeric(15, 2), nullable=False, default=0.00)  # 税额
    total_amount = Column(Numeric(15, 2), nullable=False, default=0.00)  # 价税合计

    is_export = Column(Boolean, default=False)  # 是否出口业务
    export_amount_fob = Column(Numeric(15, 2), nullable=True)  # FOB离岸价 (外币)
    export_currency = Column(String(10), nullable=True)
    export_rebate_rate = Column(Numeric(5, 4), nullable=True)  # 退税率

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Immutable audit trail for all API requests."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=True, index=True)
    ledger_id = Column(Integer, nullable=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    detail = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Salesperson(Base):
    __tablename__ = "salespersons"
    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    department = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)


class ContractStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OEMContract(Base):
    __tablename__ = "oem_contracts"
    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    contract_number = Column(String(100), nullable=False, index=True)
    salesperson_id = Column(Integer, ForeignKey("salespersons.id"), nullable=True)
    customer_name = Column(String(255), nullable=True)
    contract_date = Column(Date, nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(10), default="CNY")
    status = Column(Enum(ContractStatus, native_enum=False), default=ContractStatus.ACTIVE)
    salesperson = relationship("Salesperson")


class CommissionBasis(enum.Enum):
    REVENUE = "revenue"
    GROSS_PROFIT = "gross_profit"
    NET_PROFIT = "net_profit"


class CommissionRule(Base):
    __tablename__ = "commission_rules"
    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    salesperson_id = Column(Integer, ForeignKey("salespersons.id"), nullable=True)
    rule_name = Column(String(100), nullable=False)
    basis = Column(Enum(CommissionBasis, native_enum=False), nullable=False, default=CommissionBasis.GROSS_PROFIT)
    rate = Column(Numeric(5, 4), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    salesperson = relationship("Salesperson")


class AccountBalance(Base):
    """Pre-computed account balances per period to avoid full-scanning VoucherEntry.

    Updated at period close. Reports query this table instead of aggregating all
    voucher history from day one. Month=NULL stores annual (year-end) snapshots.
    """
    __tablename__ = "account_balances"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("ledgers.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=True)  # NULL = annual, 1-12 = monthly
    period_debit = Column(Numeric(15, 2), nullable=False, default=0)
    period_credit = Column(Numeric(15, 2), nullable=False, default=0)
    ending_debit = Column(Numeric(15, 2), nullable=False, default=0)
    ending_credit = Column(Numeric(15, 2), nullable=False, default=0)

    account = relationship("Account")

    __table_args__ = (
        UniqueConstraint("ledger_id", "account_id", "year", "month", name="uq_account_balance_period"),
    )
