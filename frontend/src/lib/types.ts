/** Shared TypeScript interfaces — single source of truth for API/domain types. */

// -- Ledger --
export interface Ledger {
  id: number;
  name: string;
  company_name: string;
  base_currency: string;
  start_year: number;
  start_month: number;
}

// -- Voucher --
export interface VoucherEntry {
  id: number;
  account_id: number;
  account: { id: number; code: string; name: string };
  summary: string;
  direction: string;
  amount: string | number;
  currency_code?: string;
  original_amount?: string | number | null;
  exchange_rate?: string | number;
}

export interface Voucher {
  id: number;
  voucher_number: string;
  voucher_date: string;
  status: string;
  contract_number?: string | null;
  attachments_count?: number;
  entries: VoucherEntry[];
}

// -- VoucherEntryDraft (for create/edit forms) --
export interface VoucherEntryDraft {
  account_code: string;
  summary: string;
  direction: string;
  amount: string;
  partner_id?: string;
  currency_code?: string;
  original_amount?: string;
  exchange_rate?: string;
}

// -- Account --
export interface AccountInfo {
  id: number;
  code: string;
  name: string;
  account_type?: string;
  balance_direction?: string;
  opening_balance?: number | string;
  is_active?: boolean;
  parent_id?: number | null;
}

// -- Upload results (AI Chat) --
export interface ProcessedInvoice {
  filename: string;
  status: string;
  doc_id: number;
  vendor_name: string;
  items: InvoiceItem[];
  message?: string;
}

export interface ProcessedStatement {
  filename: string;
  status: string;
  doc_id: number;
  bank_name: string;
  transaction_count: number;
  message?: string;
}

export interface InvoiceItem {
  item_name: string;
  amount: number | string;
  quantity?: number;
  specification?: string;
}

export interface BankTransaction {
  transaction_date: string;
  counterpart_name: string;
  amount: string;
  remarks: string;
}

// -- Reconciliation --
export interface ReconcileMatch {
  statement_item_id: number;
  invoice_item_id: number;
  confidence: number;
  reason: string;
  discrepancy_amount: number;
  discrepancy_type: string;
  source?: string;
}

// -- Currency --
export interface Currency {
  id: number;
  code: string;
  name: string;
  is_base?: boolean;
}

// -- Partner --
export interface Partner {
  id: number;
  name: string;
  type: string;
}

// -- AI Chat --
export interface ChatActionPayload {
  // SUGGEST_ACCOUNT
  proposed_code?: string;
  new_account_name?: string;
  parent_id?: number;
  parent_name?: string;
  // INVOICE_RESULT / STATEMENT_RESULT
  doc_id?: number;
  vendor_name?: string;
  bank_name?: string;
  items?: InvoiceItem[];
  transactions?: BankTransaction[];
  // RECONCILE_SUGGESTIONS
  matches?: ReconcileMatch[];
  // RECONCILE_EXECUTION
  voucher_id?: number;
}
