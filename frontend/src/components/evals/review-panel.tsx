import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Button, InlineError, Panel, PanelHead } from "@/components/ui";
import {
  bootstrapEvalSet,
  listPipelines,
  upsertEvalExample,
  type BootstrapResult,
  type ConsensusDisagreement,
  type EvalSet,
  type Pipeline,
} from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";

/**
 * The review queue — where consensus stops and a human starts.
 *
 * Bootstrap settles the boring majority; what lands here is the residue the
 * variants genuinely disagreed about, which is also the most informative
 * part of the corpus. Two design consequences follow:
 *
 * **It is keyboard-driven.** This is a volume task. A queue that needs a
 * mouse per document is a queue people abandon at row forty, and an eval set
 * abandoned halfway is the empty-corpus failure arriving late.
 *
 * **Nothing is written until a key is pressed.** The bootstrap preview
 * (`confirm: false`) writes nothing at all, so looking costs nothing. A
 * corpus is what every future comparison is measured against; filling it by
 * accident is not recoverable by re-running anything.
 */
export function ReviewPanel({ evalSet }: { evalSet: EvalSet }) {
  const { can } = usePermissions();
  const [variants, setVariants] = useState<string[]>([]);
  const [result, setResult] = useState<BootstrapResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();

  const { data: pipelines } = useSWR<Pipeline[]>(["pipelines", "eval-review"], () =>
    listPipelines(),
  );
  const evalPipelines = (pipelines ?? []).filter((p) => p.pipeline_type === "eval");

  const runBootstrap = async () => {
    setBusy(true);
    setErr(null);
    try {
      setResult(await bootstrapEvalSet(evalSet.id, variants, false));
    } catch (e) {
      setErr(humanizeError(e, { action: "run", entity: "bootstrap" }).message);
    } finally {
      setBusy(false);
    }
  };

  const acceptAgreed = async () => {
    if (!result) return;
    setBusy(true);
    try {
      const res = await bootstrapEvalSet(evalSet.id, variants, true);
      toast.success({
        title: `Wrote ${res.written} consensus labels`,
        message: `Labels are now at v${res.labels_version}.`,
      });
      setResult({ ...res });
    } catch (e) {
      toast.error(humanizeError(e, { action: "accept", entity: "consensus labels" }));
    } finally {
      setBusy(false);
    }
  };

  if (!can("eval:write")) {
    return (
      <div className="text-[13px] text-muted">
        Reviewing writes labels — you need <code className="font-mono">eval:write</code>.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Panel>
        <PanelHead label="Bootstrap from variants" />
        <div className="px-4 py-3 flex flex-col gap-3">
          <p className="text-[12.5px] text-muted">
            Run two or more configs over the corpus and keep only what they all agree on. Agreement
            uses this set&apos;s comparators, so <code className="font-mono">$1,240.50</code> and{" "}
            <code className="font-mono">1240.50</code> count as the same answer. Everything they
            disagree on lands in the queue below.
          </p>
          {evalPipelines.length < 2 ? (
            <p className="text-[12.5px] text-subtle">
              You need at least two eval pipelines to bootstrap. One config agreeing with itself is
              not evidence.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {evalPipelines.map((p) => {
                const on = variants.includes(p.id);
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() =>
                      setVariants(on ? variants.filter((v) => v !== p.id) : [...variants, p.id])
                    }
                    className="text-[12px] px-2 py-1 rounded-[var(--radius)] border transition-colors"
                    style={{
                      borderColor: on ? "var(--accent)" : "var(--border)",
                      color: on ? "var(--accent)" : "var(--muted)",
                      background: on ? "var(--accent-tint)" : "transparent",
                    }}
                  >
                    {p.name}
                  </button>
                );
              })}
            </div>
          )}
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={busy || variants.length < 2}
              onClick={() => void runBootstrap()}
            >
              {busy ? "Running…" : "Preview consensus"}
            </Button>
            {result && result.agreed.length > 0 && (
              <Button
                variant="default"
                size="sm"
                disabled={busy || !result.auto_accept}
                title={result.warning ?? undefined}
                onClick={() => void acceptAgreed()}
              >
                Accept {result.agreed.length} agreed
              </Button>
            )}
          </div>
          {err && <InlineError title="Bootstrap failed" message={err} />}
          {result?.warning && (
            <div
              className="text-[12.5px] px-3 py-2 rounded-[var(--radius)] border"
              style={{ borderColor: "var(--gold)", color: "var(--gold)" }}
            >
              {result.warning}
            </div>
          )}
          {result && (
            <p className="font-mono text-[11.5px] text-subtle tabular-nums">
              {result.n_documents} documents · {result.agreed.length} agreed ·{" "}
              {result.disagreed.length} need review
            </p>
          )}
        </div>
      </Panel>

      {result && result.disagreed.length > 0 && (
        <ReviewQueue
          evalSet={evalSet}
          items={result.disagreed}
          onResolved={(docKey) =>
            setResult({
              ...result,
              disagreed: result.disagreed.filter((d) => d.doc_key !== docKey),
            })
          }
        />
      )}
    </div>
  );
}

function ReviewQueue({
  evalSet,
  items,
  onResolved,
}: {
  evalSet: EvalSet;
  items: ConsensusDisagreement[];
  onResolved: (docKey: string) => void;
}) {
  const [cursor, setCursor] = useState(0);
  // Keyed by doc_key rather than reset on navigation: a reviewer who moves
  // on and comes back should find their adjudication intact, and a single
  // shared object would silently apply one document's choice to the next.
  const [picksByDoc, setPicksByDoc] = useState<Record<string, Record<string, unknown>>>({});
  const toast = useToast();

  const current = items[Math.min(cursor, items.length - 1)];
  const docKey = current?.doc_key;
  const picked = useMemo(() => (docKey ? (picksByDoc[docKey] ?? {}) : {}), [picksByDoc, docKey]);
  const contested = useMemo(() => (current ? Object.keys(current.candidates) : []), [current]);

  /**
   * The options a reviewer may choose, which are deliberately *not* the raw
   * candidate values.
   *
   * A variant returning nothing is not proposing "the document does not
   * state this" — it failed to answer. Offering that null beside the real
   * answers invites recording an extractor's miss as ground truth, which
   * asserts the correct answer is nothing and makes every abstaining
   * extractor score a hit on the row. `consensus()` already refuses
   * unanimous null for exactly this reason; the review path has to agree.
   *
   * Absence is still a legitimate label — a document genuinely may not
   * contain the field — so it is offered, once, worded as the assertion it
   * is rather than disguised as a variant's output.
   */
  const optionsFor = useCallback(
    (field: string) => {
      const votes = current?.candidates[field] ?? {};
      const opts: { label: string; value: unknown; from: string }[] = [];
      for (const [variant, value] of Object.entries(votes)) {
        if (value === null || value === undefined || value === "") continue;
        const existing = opts.find((o) => String(o.value) === String(value));
        if (existing) {
          existing.from = `${existing.from}, ${variant}`;
          continue;
        }
        opts.push({ label: String(value), value, from: variant });
      }
      opts.push({
        label: "Document doesn't state this",
        value: null,
        from: "asserts the field is genuinely absent",
      });
      return opts;
    },
    [current],
  );

  const pick = useCallback(
    (field: string, value: unknown) => {
      if (!docKey) return;
      setPicksByDoc((prev) => ({
        ...prev,
        [docKey]: { ...(prev[docKey] ?? {}), [field]: value },
      }));
    },
    [docKey],
  );

  const accept = useCallback(async () => {
    if (!current) return;
    const missing = contested.filter((f) => picked[f] === undefined);
    if (missing.length) {
      toast.error({
        title: "Still contested",
        message: `Pick a value for ${missing.join(", ")} before accepting.`,
      });
      return;
    }
    try {
      const res = await upsertEvalExample(evalSet.id, {
        doc_key: current.doc_key,
        // A human adjudicated this, so it is a human label — not consensus.
        // The variants disagreed; the person is the one who decided.
        labels: { ...current.agreed_fields, ...picked },
        label_source: "human",
      });
      toast.success({
        title: "Labeled",
        message: `Labels are now at v${res.labels_version}.`,
      });
      onResolved(current.doc_key);
    } catch (e) {
      toast.error(humanizeError(e, { action: "save", entity: "label" }));
    }
  }, [current, contested, picked, evalSet.id, onResolved, toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.key === "j") setCursor((c) => Math.min(c + 1, items.length - 1));
      else if (e.key === "k") setCursor((c) => Math.max(c - 1, 0));
      else if (e.key === "Enter") void accept();
      else if (/^[1-9]$/.test(e.key) && current) {
        // Number keys pick the nth candidate of the *first* contested field —
        // the common case is a single disagreement, and making that one
        // keystroke is the difference between a queue people finish and one
        // they abandon.
        const field = contested[0];
        if (!field) return;
        const opts = optionsFor(field);
        const choice = opts[Number(e.key) - 1];
        if (choice) pick(field, choice.value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [accept, items.length, current, contested, pick, optionsFor]);

  if (!current) return null;

  return (
    <Panel>
      <PanelHead label="Needs review" count={items.length} />
      <div className="px-4 py-2 border-b border-border text-[11.5px] text-subtle">
        <kbd className="font-mono">j</kbd>/<kbd className="font-mono">k</kbd> move ·{" "}
        <kbd className="font-mono">1</kbd>–<kbd className="font-mono">9</kbd> pick ·{" "}
        <kbd className="font-mono">enter</kbd> accept
      </div>

      <div className="px-4 py-3 flex flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-[12px] text-subtle">{current.doc_key.slice(0, 16)}…</span>
          <a
            href={`/documents/detail?key=${encodeURIComponent(current.doc_key)}`}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-accent hover:underline"
          >
            Open document
          </a>
          <span className="ml-auto font-mono text-[11.5px] text-subtle tabular-nums">
            {cursor + 1} of {items.length}
          </span>
        </div>

        {Object.entries(current.agreed_fields).length > 0 && (
          <div className="flex flex-wrap gap-3 text-[12px]">
            {Object.entries(current.agreed_fields).map(([f, v]) => (
              <span key={f}>
                <span className="text-subtle text-[11px]">{f} </span>
                <span className="font-mono" style={{ color: "var(--green)" }}>
                  {String(v ?? "—")}
                </span>
              </span>
            ))}
          </div>
        )}

        {contested.map((field) => (
          <div key={field} className="flex flex-col gap-1.5">
            <span className="text-[11px] text-subtle uppercase tracking-wide">{field}</span>
            <div className="flex flex-wrap gap-2">
              {optionsFor(field).map((opt, i) => {
                const on = picked[field] !== undefined && picked[field] === opt.value;
                const absent = opt.value === null;
                return (
                  <button
                    key={`${field}-${i}`}
                    type="button"
                    onClick={() => pick(field, opt.value)}
                    className="text-left px-2.5 py-1.5 rounded-[var(--radius)] border transition-colors"
                    style={{
                      borderColor: on ? "var(--accent)" : absent ? "var(--gold)" : "var(--border)",
                      background: on ? "var(--accent-tint)" : "transparent",
                    }}
                  >
                    <span className="font-mono text-[11px] text-subtle">{i + 1} </span>
                    <span
                      className="font-mono text-[12.5px]"
                      style={absent ? { color: "var(--gold)" } : undefined}
                    >
                      {opt.label}
                    </span>
                    <span className="block text-[10.5px] text-subtle">{opt.from}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        <div className="flex items-center gap-2 pt-1">
          <Button variant="primary" size="sm" onClick={() => void accept()} kbd="↵">
            Accept as label
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setCursor((c) => Math.min(c + 1, items.length - 1))}
          >
            Skip
          </Button>
        </div>
      </div>
    </Panel>
  );
}
