// Types for every object in docs/SPEC.md. Field names mirror the API exactly
// (snake_case as delivered); do not rename. Optional (`?`) marks fields the SPEC
// shows in examples but does not guarantee; nullable marks fields the SPEC
// allows to be null.

// ---------------------------------------------------------------- enums
export type Decision = 'APPROVE' | 'HOLD' | 'REJECT';
export type RunStatus = 'queued' | 'running' | 'completed' | 'failed';
export type StageStatus = 'pending' | 'running' | 'done' | 'warn' | 'failed' | 'skipped';
export type StageKey = 'intake' | 'doc_analysis' | 'extraction' | 'integrity' | 'matching' | 'rules' | 'decision';
export type DocumentClass = 'digital' | 'scanned' | 'mixed';
export type RuleSeverity = 'REJECT' | 'HOLD' | 'WARN';
export type RuleCode = 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'R6' | 'R7' | 'R8' | 'R9' | 'R10';
export type VendorMatchMethod = 'tax_id' | 'alias' | 'name_fuzzy' | 'none';
export type PoMatchMethod = 'explicit' | 'inferred' | 'ambiguous' | 'none' | 'not_found';
export type ActionOwner = 'ap' | 'requester' | 'vendor' | 'none';
export type VendorStatus = 'approved' | 'suspended';
export type PoStatus = 'open' | 'closed';
export type LedgerSource = 'seed' | 'run';

// ---------------------------------------------------------------- §2 reference data
export interface Vendor {
  vendor_id: string;
  legal_name: string;
  aliases: string; // pipe-separated
  tax_id: string;
  country: string;
  currency: string;
  status: VendorStatus;
  payment_terms_days: number;
  contact_email: string;
}

export interface PoLine {
  po_number: string;
  line_no: number;
  description: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface PoInvoiceRef {
  invoice_number: string | null;
  net_total: number;
  decision: Decision;
  source: LedgerSource;
}

/** `GET /api/reference/pos` item: purchase_orders.csv row + lines + billing state. */
export interface PurchaseOrder {
  po_number: string;
  vendor_id: string;
  po_date: string;
  currency: string;
  net_total: number;
  status: PoStatus;
  requester_name: string;
  requester_email: string;
  description: string;
  lines: PoLine[];
  billed_net_to_date: number;
  remaining_net: number;
  invoices: PoInvoiceRef[];
}

export interface LedgerRow {
  id?: number;
  invoice_number: string | null;
  vendor_id: string | null;
  invoice_date: string | null;
  currency: string | null;
  net_total: number | null;
  gross_total: number | null;
  po_number: string | null;
  decision: Decision;
  file_hash: string | null;
  processed_at: string;
  source?: LedgerSource;
  run_id?: string | null;
}

/** `GET /api/samples` item: samples.json entry plus `url`. */
export interface Sample {
  id: string;
  title: string;
  scenario: string;
  file: string;
  vendor_id: string | null;
  expected_decision: Decision;
  expected_rule_failures: string[];
  demo_order: number;
  notes: string;
  url: string;
}

// ---------------------------------------------------------------- §3 extraction
export interface Evidence {
  quote: string;
  page: number;
}

export interface StrField {
  value: string | null;
  confidence: number;
  evidence: Evidence | null;
}

export interface NumField {
  value: number | null;
  confidence: number;
  evidence: Evidence | null;
}

export interface LineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  confidence: number;
}

export interface InvoiceExtraction {
  vendor_name: StrField;
  vendor_tax_id: StrField;
  vendor_address: StrField;
  bill_to_name: StrField;
  invoice_number: StrField;
  invoice_date: StrField;
  due_date: StrField;
  currency: StrField;
  po_references: string[];
  line_items: LineItem[];
  subtotal: NumField;
  tax_amount: NumField;
  tax_rate_pct: NumField;
  total: NumField;
  payment_terms: StrField;
  document_notes: string;
  overall_confidence: number;
}

// ---------------------------------------------------------------- §4 stage outputs
export interface IntakeOutput {
  filename: string;
  size_bytes: number;
  sha256: string;
  page_count: number;
  sample_id: string | null;
}

export interface PageInfo {
  page: number;
  chars: number;
  has_text_layer: boolean;
}

export interface DocAnalysisOutput {
  document_class: DocumentClass;
  pages: PageInfo[];
  text_layer: string;
  language_guess: string;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ExtractionOutput {
  model: string;
  extraction?: InvoiceExtraction | null;
  /** Empty when a cached extraction carried no usage record. */
  usage?: Partial<TokenUsage> | null;
  from_cache: boolean;
  latency_ms: number;
}

export interface NormalisedLineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
}

export interface NormalisedInvoice {
  vendor_name: string | null;
  vendor_tax_id: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  po_references: string[];
  po_references_normalised: string[];
  subtotal: number | null;
  tax_amount: number | null;
  total: number | null;
  line_items: NormalisedLineItem[];
}

export type IntegrityCheckCode = 'lines_sum_subtotal' | 'subtotal_tax_total' | 'required_fields' | 'date_parse';

export interface IntegrityCheck {
  code: IntegrityCheckCode | string;
  passed: boolean;
  detail: string;
}

/** A field is null when absent from the invoice; min is null when all three are. */
export interface CriticalConfidence {
  invoice_number: number | null;
  total: number | null;
  vendor_name: number | null;
  min: number | null;
}

export interface IntegrityOutput {
  normalised?: NormalisedInvoice | null;
  checks?: IntegrityCheck[] | null;
  critical_confidence?: CriticalConfidence | null;
}

export interface VendorCandidate {
  vendor_id: string;
  score: number;
  method: VendorMatchMethod | string;
}

export interface VendorMatch {
  matched: boolean;
  vendor_id: string | null;
  legal_name: string | null;
  status: VendorStatus | null;
  method: VendorMatchMethod | string;
  score: number;
  candidates: VendorCandidate[];
}

/** SPEC lists `candidates` for inferred/ambiguous POs without fixing its shape. */
export interface PoCandidate {
  po_number: string;
  score: number;
  amount_score?: number;
  line_score?: number;
  net_total?: number;
  remaining_net?: number;
}

export interface LineMatch {
  invoice_line: number;
  po_line: number;
  score: number;
}

export interface PoMatch {
  matched: boolean;
  po_number: string | null;
  method: PoMatchMethod;
  score: number;
  status: PoStatus | null;
  vendor_id: string | null;
  vendor_mismatch: boolean;
  net_total: number | null;
  billed_net_to_date: number | null;
  remaining_net: number | null;
  candidates: PoCandidate[];
  line_matches: LineMatch[];
  unmatched_invoice_lines: number[];
}

export interface MatchingOutput {
  vendor?: VendorMatch | null;
  po?: PoMatch | null;
}

export interface RuleResult {
  code: RuleCode | string;
  name: string;
  /** null when the rule was skipped. */
  passed: boolean | null;
  severity: RuleSeverity;
  detail: string;
  evidence: Record<string, unknown> | null;
  skipped?: boolean;
}

export interface RulesOutput {
  results?: RuleResult[] | null;
  failed_hold: string[];
  failed_reject: string[];
  warnings?: string[] | null;
}

export interface DecisionReason {
  code: string;
  text: string;
}

export interface NextAction {
  owner: ActionOwner;
  text: string;
}

export interface DraftEmail {
  to: string;
  subject: string;
  body: string;
}

export interface Booking {
  po_number: string | null;
  net_amount: number | null;
  gross_amount: number | null;
  currency: string | null;
  po_remaining_after: number | null;
}

export interface DecisionOutput {
  decision: Decision;
  confidence: number;
  reasons: DecisionReason[];
  warnings: string[];
  explanation: string;
  next_action: NextAction;
  draft_email: DraftEmail | null;
  booking: Booking | null;
}

export interface StageOutputMap {
  intake: IntakeOutput;
  doc_analysis: DocAnalysisOutput;
  extraction: ExtractionOutput;
  integrity: IntegrityOutput;
  matching: MatchingOutput;
  rules: RulesOutput;
  decision: DecisionOutput;
}

export interface StageRecord<K extends StageKey = StageKey> {
  key: K;
  index: number;
  name: string;
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  summary: string;
  warnings: string[];
  output: StageOutputMap[K] | null;
}

// ---------------------------------------------------------------- §5 API
export interface ApiError {
  error: { code: string; message: string };
}

export interface Health {
  ok: boolean;
  model: string;
  db: string;
}

export interface CreateRunResponse {
  run_id: string;
}

export interface RunSummary {
  id: string;
  created_at: string;
  filename: string;
  sample_id: string | null;
  file_hash: string | null;
  status: RunStatus;
  document_class: DocumentClass | null;
  decision: Decision | null;
  confidence: number | null;
  vendor_name: string | null;
  vendor_id: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  net_total: number | null;
  gross_total: number | null;
  po_number: string | null;
  duration_ms: number | null;
  current_stage: StageKey | null;
  error: string | null;
  /** Reviewer override of a HOLD; `decision` stays the pipeline's own answer. */
  override_decision: Exclude<Decision, 'HOLD'> | null;
  override_note: string | null;
  override_by: string | null;
  override_at: string | null;
  /** Booking computed at override time for an APPROVE override, else null. */
  override_booking: Booking | null;
  /** override_decision if set, else decision. */
  final_decision: Decision | null;
}

export interface OverrideRequest {
  decision: Exclude<Decision, 'HOLD'>;
  note: string;
  reviewer: string;
}

export interface RunDetail extends RunSummary {
  stages: StageRecord[];
}

export interface RunList {
  items: RunSummary[];
  total: number;
}

export interface Stats {
  runs: number;
  approve: number;
  hold: number;
  reject: number;
  auto_approval_rate: number;
  median_duration_ms: number;
  last_24h: number;
}

/** GET /api/policy: the loaded config.yaml values, read-only. */
export interface PolicySettings {
  policy: {
    tolerance_pct: number;
    tolerance_abs_floor: Record<string, number>;
    confidence_floor: number;
    date_window_days: number;
    future_date_grace_days: number;
    duplicate_date_window_days: number;
    scanned_chars_per_page: number;
  };
  extraction: { model: string; effort: string; cache_fallback: boolean };
}

// ---------------------------------------------------------------- §6 SSE
export interface RunStartedData {
  run_id: string;
  created_at: string;
  filename: string;
  sample_id: string | null;
}
export interface StageEventData {
  run_id: string;
  stage: StageRecord;
}
export interface StageFailedData extends StageEventData {
  error: string;
}
export interface RunCompletedData {
  run_id: string;
  summary: RunSummary;
  decision: DecisionOutput;
}
export interface RunFailedData {
  run_id: string;
  error: string;
  summary: RunSummary;
}
export interface OverrideData {
  run_id: string;
  summary: RunSummary;
}

export type RunEvent =
  | { seq: number; type: 'run.started'; data: RunStartedData }
  | { seq: number; type: 'stage.started'; data: StageEventData }
  | { seq: number; type: 'stage.completed'; data: StageEventData }
  | { seq: number; type: 'stage.failed'; data: StageFailedData }
  | { seq: number; type: 'run.completed'; data: RunCompletedData }
  | { seq: number; type: 'run.failed'; data: RunFailedData }
  | { seq: number; type: 'override'; data: OverrideData };

export type RunEventType = RunEvent['type'];
