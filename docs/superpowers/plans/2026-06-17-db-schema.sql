-- =============================================================================
-- Trad Account — Database Schema DDL
-- Target: PostgreSQL (production) / SQLite (dev/test with SQLAlchemy compatible)
-- Enum types are handled by SQLAlchemy Enum; this DDL uses CHECK constraints
-- for readability when applied directly.
-- =============================================================================

-- =============================================================================
-- USERS
-- =============================================================================
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        VARCHAR(100) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'accountant'
                    CHECK (role IN ('admin', 'accountant', 'auditor')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    token_version   INTEGER NOT NULL DEFAULT 0,
    last_login      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_users_username ON users(username);

-- =============================================================================
-- LEDGERS (账套)
-- =============================================================================
CREATE TABLE ledgers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            VARCHAR(255) NOT NULL,
    company_name    VARCHAR(255),
    base_currency   VARCHAR(10) NOT NULL DEFAULT 'CNY',
    start_year      INTEGER NOT NULL,
    start_month     INTEGER NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    llm_provider    VARCHAR(50) DEFAULT 'deepseek',
    llm_api_key     VARCHAR(512),  -- encrypted at rest via Fernet
    llm_base_url    VARCHAR(255),
    llm_model_name  VARCHAR(100) DEFAULT 'deepseek-chat',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- ACCOUNTS (Chart of Accounts — 科目表, hierarchical)
-- =============================================================================
CREATE TABLE accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id        INTEGER NOT NULL REFERENCES ledgers(id),
    code             VARCHAR(50) NOT NULL,
    name             VARCHAR(255) NOT NULL,
    parent_id        INTEGER REFERENCES accounts(id),
    account_type     VARCHAR(20) NOT NULL
                     CHECK (account_type IN ('ASSET','LIABILITY','EQUITY','COST','PROFIT_LOSS')),
    balance_direction VARCHAR(10) NOT NULL
                     CHECK (balance_direction IN ('DEBIT','CREDIT')),
    opening_balance  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_accounts_ledger     ON accounts(ledger_id);
CREATE INDEX ix_accounts_code       ON accounts(code);
CREATE INDEX ix_accounts_parent     ON accounts(parent_id);

-- =============================================================================
-- BUSINESS PARTNERS (往来单位 — 客户/供应商)
-- =============================================================================
CREATE TABLE business_partners (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id    INTEGER NOT NULL REFERENCES ledgers(id),
    code         VARCHAR(50) NOT NULL,
    name         VARCHAR(255) NOT NULL,
    partner_type VARCHAR(10) NOT NULL
                 CHECK (partner_type IN ('CUSTOMER','VENDOR','BOTH')),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_partners_ledger ON business_partners(ledger_id);
CREATE INDEX ix_partners_code   ON business_partners(code);

-- =============================================================================
-- VOUCHERS (会计凭证)
-- =============================================================================
CREATE TABLE vouchers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id         INTEGER NOT NULL REFERENCES ledgers(id),
    voucher_number    VARCHAR(50) NOT NULL,
    voucher_date      DATE NOT NULL,
    attachments_count INTEGER NOT NULL DEFAULT 0,
    status            VARCHAR(20) NOT NULL DEFAULT 'DRAFT'
                      CHECK (status IN ('DRAFT','APPROVED','POSTED')),
    source_type       VARCHAR(50),
    contract_number   VARCHAR(100)
);
CREATE INDEX ix_vouchers_ledger  ON vouchers(ledger_id);
CREATE INDEX ix_vouchers_number  ON vouchers(voucher_number);
CREATE INDEX ix_vouchers_status  ON vouchers(status);
CREATE INDEX ix_vouchers_date    ON vouchers(voucher_date);
CREATE INDEX ix_vouchers_contract ON vouchers(contract_number);

-- =============================================================================
-- VOUCHER ENTRIES (凭证分录)
-- =============================================================================
CREATE TABLE voucher_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id      INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    partner_id      INTEGER REFERENCES business_partners(id),
    summary         VARCHAR(255) NOT NULL,
    direction       VARCHAR(10) NOT NULL
                    CHECK (direction IN ('DEBIT','CREDIT')),
    amount          DECIMAL(15,2) NOT NULL,
    currency_code   VARCHAR(10) NOT NULL DEFAULT 'CNY',
    original_amount DECIMAL(15,2),
    exchange_rate   DECIMAL(10,4) NOT NULL DEFAULT 1.0000,
    vat_rate        DECIMAL(5,4),
    vat_amount      DECIMAL(15,2)
);
CREATE INDEX ix_entries_voucher  ON voucher_entries(voucher_id);
CREATE INDEX ix_entries_account  ON voucher_entries(account_id);
CREATE INDEX ix_entries_partner  ON voucher_entries(partner_id);

-- =============================================================================
-- ORIGINAL DOCUMENTS (原始凭证 — 发票/流水)
-- =============================================================================
CREATE TABLE original_documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id        INTEGER NOT NULL REFERENCES ledgers(id),
    doc_type         VARCHAR(50) NOT NULL,
    file_path        VARCHAR(500) NOT NULL,
    extracted_data   JSON,
    is_reconciled    BOOLEAN NOT NULL DEFAULT FALSE,
    related_voucher_id INTEGER REFERENCES vouchers(id)
);
CREATE INDEX ix_docs_ledger ON original_documents(ledger_id);

-- =============================================================================
-- OPEN ITEMS (未清项 — 往来款对账)
-- =============================================================================
CREATE TABLE open_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id           INTEGER NOT NULL REFERENCES ledgers(id),
    item_type           VARCHAR(20) NOT NULL
                        CHECK (item_type IN ('INVOICE','BANK_TXN')),
    source_doc_id       INTEGER REFERENCES original_documents(id),
    txn_index           INTEGER,
    date                DATE NOT NULL,
    counterpart_name    VARCHAR(255),
    remarks             VARCHAR(255),
    amount              DECIMAL(15,2) NOT NULL,
    unreconciled_amount DECIMAL(15,2) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN','PARTIAL','CLEARED'))
);
CREATE INDEX ix_open_items_ledger ON open_items(ledger_id);

-- =============================================================================
-- RECONCILIATION RECORDS (对账记录 — 勾稽关系)
-- =============================================================================
CREATE TABLE reconciliation_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id           INTEGER NOT NULL REFERENCES ledgers(id),
    reconciled_date     DATE NOT NULL,
    invoice_item_id     INTEGER NOT NULL REFERENCES open_items(id),
    statement_item_id   INTEGER NOT NULL REFERENCES open_items(id),
    matched_amount      DECIMAL(15,2) NOT NULL,
    discrepancy_amount  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    discrepancy_type    VARCHAR(50),
    clearing_voucher_id INTEGER REFERENCES vouchers(id)
);
CREATE INDEX ix_recon_ledger ON reconciliation_records(ledger_id);

-- =============================================================================
-- VOUCHER NUMBER COUNTERS (凭证号计数器 — per-ledger, per-prefix)
-- =============================================================================
CREATE TABLE voucher_number_counters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id      INTEGER NOT NULL REFERENCES ledgers(id),
    prefix         VARCHAR(20) NOT NULL,
    current_number INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX ix_vn_counter_ledger_prefix ON voucher_number_counters(ledger_id, prefix);

-- =============================================================================
-- FIXED ASSETS (固定资产)
-- =============================================================================
CREATE TABLE fixed_assets (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id                INTEGER NOT NULL REFERENCES ledgers(id),
    asset_code               VARCHAR(50) NOT NULL,
    asset_name               VARCHAR(255) NOT NULL,
    purchase_date            DATE NOT NULL,
    original_value           DECIMAL(15,2) NOT NULL,
    salvage_value_rate       DECIMAL(5,4) NOT NULL DEFAULT 0.0500,
    expected_useful_months   INTEGER NOT NULL,
    accumulated_depreciation DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    is_active                BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_assets_ledger ON fixed_assets(ledger_id);
CREATE INDEX ix_assets_code   ON fixed_assets(asset_code);

-- =============================================================================
-- ACCOUNTING PERIODS (会计期间)
-- =============================================================================
CREATE TABLE accounting_periods (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id INTEGER NOT NULL REFERENCES ledgers(id),
    year      INTEGER NOT NULL,
    month     INTEGER NOT NULL,
    status    VARCHAR(10) NOT NULL DEFAULT 'OPEN'
              CHECK (status IN ('OPEN','CLOSED'))
);
CREATE UNIQUE INDEX ix_periods_ledger_ym ON accounting_periods(ledger_id, year, month);

-- =============================================================================
-- CURRENCIES (币种)
-- =============================================================================
CREATE TABLE currencies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     VARCHAR(10) NOT NULL UNIQUE,
    name     VARCHAR(50) NOT NULL,
    is_base  BOOLEAN NOT NULL DEFAULT FALSE
);

-- =============================================================================
-- EXCHANGE RATES (汇率)
-- =============================================================================
CREATE TABLE exchange_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id   INTEGER NOT NULL REFERENCES accounting_periods(id),
    currency_id INTEGER NOT NULL REFERENCES currencies(id),
    rate        DECIMAL(10,4) NOT NULL
);

-- =============================================================================
-- TAX RATES (税率)
-- =============================================================================
CREATE TABLE tax_rates (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id      INTEGER NOT NULL REFERENCES ledgers(id),
    tax_type       VARCHAR(30) NOT NULL
                   CHECK (tax_type IN ('vat_input','vat_output','export_rebate')),
    rate           DECIMAL(5,4) NOT NULL,
    description    VARCHAR(100),
    effective_from DATE NOT NULL,
    effective_to   DATE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_tax_rates_ledger ON tax_rates(ledger_id);

-- =============================================================================
-- VAT RECORDS (增值税记录 — 纳税申报)
-- =============================================================================
CREATE TABLE vat_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id         INTEGER NOT NULL REFERENCES ledgers(id),
    voucher_id        INTEGER NOT NULL REFERENCES vouchers(id),
    voucher_date      DATE NOT NULL,
    vat_type          VARCHAR(20) NOT NULL
                      CHECK (vat_type IN ('input','output')),
    invoice_code      VARCHAR(50),
    invoice_number    VARCHAR(50),
    counterpart_name  VARCHAR(255),
    taxable_amount    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    vat_rate          DECIMAL(5,4) NOT NULL DEFAULT 0.00,
    vat_amount        DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_amount      DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    is_export         BOOLEAN NOT NULL DEFAULT FALSE,
    export_amount_fob DECIMAL(15,2),
    export_currency   VARCHAR(10),
    export_rebate_rate DECIMAL(5,4),
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_vat_ledger ON vat_records(ledger_id);
CREATE INDEX ix_vat_voucher ON vat_records(voucher_id);
CREATE INDEX ix_vat_date   ON vat_records(voucher_date);

-- =============================================================================
-- CLOSING OPERATIONS (结账操作记录 — 幂等性)
-- =============================================================================
CREATE TABLE closing_operations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id       INTEGER NOT NULL REFERENCES ledgers(id),
    operation_type  VARCHAR(30) NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    voucher_id      INTEGER REFERENCES vouchers(id),
    result_message  VARCHAR(500),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_closing_ledger ON closing_operations(ledger_id);

-- =============================================================================
-- AUDIT LOGS (审计日志 — immutable)
-- =============================================================================
CREATE TABLE audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    VARCHAR(100),
    ledger_id   INTEGER,
    method      VARCHAR(10) NOT NULL,
    path        VARCHAR(500) NOT NULL,
    status_code INTEGER NOT NULL,
    detail      JSON,
    ip_address  VARCHAR(45),
    duration_ms INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_audit_username ON audit_logs(username);
CREATE INDEX ix_audit_created  ON audit_logs(created_at);

-- =============================================================================
-- OEM CONTRACTS & COMMISSION RULES (placeholder — to be added in M3/M4)
-- These tables are planned for the OEM workflow and commission engine.
-- =============================================================================
-- CREATE TABLE oem_contracts (...);
-- CREATE TABLE commission_rules (...);
