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
  /** What breaks today, before DTE. Written to the person who owns the
   *  number, not the person doing the typing. */
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
    headline: "Match every invoice before you approve it",
    lede:
      "Someone eyeballs the PO, the receipt, the invoice, and signs off. Most of the time that's fine. The exceptions are what end up in reconciliation, weeks later, as a number nobody can explain.",
    pains: [
      "Volume went up. Headcount didn't.",
      "You approve the run trusting the match happened. Usually it did.",
      "The overbill shows up in reconciliation, after the money's gone.",
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
      { label: "Auto-matched", hint: "PO, receipt, and invoice matched without manual entry" },
      { label: "Exceptions surfaced", hint: "Only mismatches reach your team, not every invoice" },
      { label: "Full lineage", hint: "Every match traces back to the source document" },
      { label: "Runs on schedule", hint: "Processing happens automatically, not when remembered" },
    ],
  },
  {
    slug: "purchase-compliance",
    dept: "Procurement",
    pick: "Purchase requisition & PO compliance",
    title: "Purchase requisition & PO compliance",
    headline: "Prove the rate you negotiated held",
    lede:
      "You negotiated the discount. Nobody checks whether purchasing actually used it. DTE reads contracts and requisitions into one table, so the gap between agreed and paid is a query, not a guess.",
    pains: [
      "You negotiated the rate. Nobody checks if purchasing used it.",
      "Finance asks where the savings went. The answer's buried in PDFs.",
      "Maverick spend is a number you estimate, not a line item you can show.",
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
      { label: "Rates enforced", hint: "Every requisition checked against the contracted price" },
      { label: "Savings visible", hint: "See the gap between agreed and paid, by line item" },
      { label: "Spend flagged", hint: "Off-contract purchases surface instead of hiding in PDFs" },
      { label: "One source of truth", hint: "Contracts and requisitions live in the same table" },
    ],
  },
  {
    slug: "employee-documents",
    dept: "HR & People Ops",
    pick: "Employee document & background-check review",
    title: "Employee document & background-check review",
    headline: "Know who's compliant before the audit",
    lede:
      "Someone asks if every employee's paperwork is current. Today that's a week of digging, and the answer is still a guess. DTE reads the files as they land and keeps the answer live.",
    pains: [
      "A shift got worked on a license that expired months ago.",
      "“Is everyone compliant” takes a week to answer. It's still a guess.",
      "The fine isn't the worry. Explaining it to the board is.",
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
      { label: "Docs stay current", hint: "Licenses and certifications tracked as they expire" },
      { label: "Answers on demand", hint: "Compliance status is a query, not a week of digging" },
      { label: "Expirations flagged", hint: "Expired credentials surface before the shift is worked" },
      { label: "Audit-ready", hint: "Evidence assembled before the auditor asks for it" },
    ],
  },
  {
    slug: "claims-processing",
    dept: "Insurance & Healthcare",
    pick: "Claims processing & medical bill review",
    title: "Claims processing & medical bill review",
    headline: "Price every claim line before you pay",
    lede:
      "Adjusters spend their day retyping bills instead of deciding claims. DTE checks every line against the fee schedule and the policy first, so the desk only sees what actually needs judgment.",
    pains: [
      "Leakage is something the auditors find, not you.",
      "You need more capacity. Nobody's handing you more adjusters.",
      "The same procedure gets billed twice, caught after payout, if ever.",
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
      { label: "Auto-priced", hint: "Every line checked against fee schedule and policy" },
      { label: "Desk sees exceptions", hint: "Only lines needing judgment reach the adjuster" },
      { label: "Duplicates caught", hint: "Repeat billing flagged before payout, not after" },
      { label: "Leakage visible", hint: "See where the money's going before the audit does" },
    ],
  },
  {
    slug: "kyc-verification",
    dept: "Compliance & Risk",
    pick: "KYC document verification",
    title: "KYC document verification",
    headline: "Walk into the exam with evidence ready",
    lede:
      "You sign the attestation. Behind it is a spreadsheet you didn't build and a folder nobody's opened since onboarding. DTE turns those packs into a table you can actually stand behind.",
    pains: [
      "The review backlog grows faster than the team clears it.",
      "One finding costs more than the fix that would've prevented it.",
      "You attest to the controls. You're trusting a spreadsheet to be current.",
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
      { label: "Packs structured", hint: "Documents turned into a table you can query" },
      { label: "Backlog shrinks", hint: "Periodic reviews keep pace instead of piling up" },
      { label: "Evidence on file", hint: "Every attestation backed by a traceable document" },
      { label: "Always current", hint: "Status reflects the latest documents, not onboarding" },
    ],
  },
];

export const findUseCase = (slug: string) => USE_CASES.find((u) => u.slug === slug);
