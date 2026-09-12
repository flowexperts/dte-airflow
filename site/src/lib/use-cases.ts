/** One use case per department. Keep this list to five — the first-visit
 *  picker shows every entry, and a sixth turns a decision into a menu. */
export type UseCase = {
  slug: string;
  dept: string;
  /** Picker label — short enough to read at a glance. */
  pick: string;
  title: string;
  headline: string;
  lede: string;
  /** What breaks today, before DTE. */
  pains: string[];
  /** The pipeline, as it reads in the builder. */
  steps: { op: string; expr: string }[];
  /** What the pipeline leaves behind. */
  outcomes: { label: string; hint: string }[];
};

export const USE_CASES: UseCase[] = [
  {
    slug: "invoice-matching",
    dept: "Finance · Accounts Payable",
    pick: "Invoice processing & 3-way matching",
    title: "Invoice processing & 3-way matching",
    headline: "Invoices in. Matched lines out.",
    lede:
      "Pull vendor invoice PDFs, turn them into typed columns, and match every line against the purchase order and the goods receipt — before anyone approves a payment.",
    pains: [
      "Invoice PDFs get keyed into the ERP by hand, one line at a time.",
      "PO, receipt and invoice live in three systems nobody joins.",
      "Price and quantity breaks surface after payment, not before.",
    ],
    steps: [
      { op: "source", expr: "s3://ap-inbox/invoices/*.pdf" },
      { op: "extract", expr: "pdf → text" },
      { op: "structure", expr: "invoice_no · vendor · line_total · qty" },
      { op: "join", expr: "purchase_orders on po_no" },
      { op: "join", expr: "goods_receipts on po_no, sku" },
      { op: "check", expr: "abs(invoice_total − po_total) < 0.01" },
      { op: "destination", expr: "postgres://erp.ap.matched_lines" },
    ],
    outcomes: [
      { label: "Three-way match", hint: "Invoice, PO and receipt reconciled line by line" },
      { label: "Exceptions only", hint: "Clean lines pass; breaks route to a review table" },
      { label: "Price & qty checks", hint: "Tolerance rules as assertions, not spreadsheets" },
      { label: "Audit trail", hint: "Every run keeps the source file and the matched row" },
    ],
  },
  {
    slug: "purchase-compliance",
    dept: "Procurement",
    pick: "Purchase requisition & PO compliance",
    title: "Purchase requisition & PO compliance",
    headline: "Every requisition, checked against policy.",
    lede:
      "Read requisitions, quotes and signed vendor agreements, then test each one against your spend thresholds, approved-vendor list and contracted rates.",
    pains: [
      "Quotes and agreements sit as PDFs nobody can query.",
      "Off-contract spend is found in a quarterly review, months late.",
      "Approval thresholds are enforced by memory and goodwill.",
    ],
    steps: [
      { op: "source", expr: "gcs://procurement/requisitions/*.pdf" },
      { op: "structure", expr: "requester · vendor · amount · cost_centre" },
      { op: "join", expr: "approved_vendors on vendor_id" },
      { op: "join", expr: "contract_rates on vendor_id, sku" },
      { op: "check", expr: "amount <= approval_limit" },
      { op: "check", expr: "unit_price <= contracted_rate" },
      { op: "destination", expr: "postgres://spend.compliance_flags" },
    ],
    outcomes: [
      { label: "Approved-vendor test", hint: "Unlisted vendors flagged the day they appear" },
      { label: "Rate adherence", hint: "Quoted price checked against the signed contract" },
      { label: "Threshold rules", hint: "Approval limits enforced per cost centre" },
      { label: "Maverick spend", hint: "Off-contract purchases surface in the run, not the audit" },
    ],
  },
  {
    slug: "employee-documents",
    dept: "HR & People Ops",
    pick: "Employee document & background-check review",
    title: "Employee document & background-check review",
    headline: "Onboarding documents, verified in one pass.",
    lede:
      "Turn offer letters, ID documents, certifications and background-check reports into rows, then check completeness and expiry against your roster automatically.",
    pains: [
      "Document chasing is a checklist in someone's inbox.",
      "Certification expiry is noticed when an auditor asks.",
      "Background-check reports are read once and never queried again.",
    ],
    steps: [
      { op: "source", expr: "s3://people-ops/onboarding/*.pdf" },
      { op: "structure", expr: "employee_id · doc_type · issued · expires" },
      { op: "join", expr: "roster on employee_id" },
      { op: "check", expr: "doc_type IN required_docs" },
      { op: "check", expr: "expires > current_date + 30" },
      { op: "aggregate", expr: "count(doc_type) by employee_id" },
      { op: "destination", expr: "postgres://hris.document_status" },
    ],
    outcomes: [
      { label: "Completeness", hint: "Missing documents listed per employee, per run" },
      { label: "Expiry watch", hint: "Certifications flagged 30 days out, on a schedule" },
      { label: "Right-to-work", hint: "ID fields extracted and matched to the roster" },
      { label: "Audit-ready", hint: "One table answers what HR holds for whom" },
    ],
  },
  {
    slug: "claims-processing",
    dept: "Insurance & Healthcare",
    pick: "Claims processing & medical bill review",
    title: "Claims processing & medical bill review",
    headline: "Claims and bills, priced against the policy.",
    lede:
      "Extract claim forms and itemised medical bills, join them to coverage and fee schedules, and let the rules decide what pays, what reduces, and what gets a human.",
    pains: [
      "Adjusters re-key bill line items before they can price anything.",
      "Duplicate and unbundled charges slip through on volume.",
      "Coverage limits are applied by hand, claim by claim.",
    ],
    steps: [
      { op: "source", expr: "s3://claims/intake/*.pdf" },
      { op: "structure", expr: "claim_no · member_id · cpt_code · charge" },
      { op: "join", expr: "policies on member_id" },
      { op: "join", expr: "fee_schedule on cpt_code" },
      { op: "check", expr: "charge <= allowed_amount" },
      { op: "check", expr: "count(*) by claim_no, cpt_code = 1" },
      { op: "destination", expr: "postgres://claims.adjudicated" },
    ],
    outcomes: [
      { label: "Line-level pricing", hint: "Each charge tested against the fee schedule" },
      { label: "Duplicate detection", hint: "Repeat codes on a claim caught before payment" },
      { label: "Coverage limits", hint: "Policy caps and exclusions applied as rules" },
      { label: "Adjuster queue", hint: "Only the exceptions reach a person" },
    ],
  },
  {
    slug: "kyc-verification",
    dept: "Compliance & Risk",
    pick: "KYC document verification",
    title: "KYC document verification",
    headline: "KYC packs, turned into evidence you can query.",
    lede:
      "Read identity documents, proof of address and incorporation papers into typed columns, match them to the customer record, and keep a dated trail of every check.",
    pains: [
      "Onboarding packs are PDFs in a folder, not data in a system.",
      "Refresh cycles are tracked in a spreadsheet that drifts.",
      "Proving a check happened means opening files one by one.",
    ],
    steps: [
      { op: "source", expr: "s3://kyc/customer-packs/*.pdf" },
      { op: "structure", expr: "customer_id · doc_type · name · dob · expiry" },
      { op: "join", expr: "customers on customer_id" },
      { op: "check", expr: "name = registered_name" },
      { op: "check", expr: "expiry > current_date" },
      { op: "profile", expr: "null % by doc_type" },
      { op: "destination", expr: "postgres://compliance.kyc_status" },
    ],
    outcomes: [
      { label: "Identity match", hint: "Extracted names and dates tested against the record" },
      { label: "Expiry & refresh", hint: "Stale documents surface on every scheduled run" },
      { label: "Pack completeness", hint: "Missing evidence listed per customer" },
      { label: "Regulator-ready", hint: "Every check dated, sourced and reproducible" },
    ],
  },
];

export const findUseCase = (slug: string) => USE_CASES.find((u) => u.slug === slug);
