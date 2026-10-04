import { useState } from "react";
import { useRouter } from "@/lib/nav";
import useSWR from "swr";
import {
  Button,
  Dropdown,
  Field,
  InlineError,
  Input,
  PageHeader,
  Panel,
  PanelHead,
  Topbar,
} from "@/components/ui";
import { createEvalSet, listSources, type Source } from "@/lib/api";
import { humanizeError, type HumanError } from "@/lib/errors";
import {
  FIELD_TYPES,
  toEvalSetPayload,
  validateEvalSetForm,
  type EvalSetDraft,
  type FieldDraft,
} from "@/lib/eval-set-form";

const emptyField = (): FieldDraft => ({ name: "", type: "string", description: "" });

/**
 * Create an eval set — the labeled corpus a pipeline gets scored against.
 *
 * The two halves of an eval are created separately (the corpus here, the
 * pipeline in the builder) and joined by **field name**, so this form leans
 * hard on making that join visible. A field named here and not emitted by
 * the pipeline's `structure` step doesn't error — it scores zero forever,
 * which looks identical to a broken extractor.
 */
export function EvalSetForm() {
  const router = useRouter();
  const [draft, setDraft] = useState<EvalSetDraft>({
    id: "",
    name: "",
    source_id: "",
    fields: [emptyField()],
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<HumanError | null>(null);

  const { data: sources } = useSWR<Source[]>("sources:documents", () => listSources());
  // The backend refuses a non-documents source; offering one here would make
  // the UI the source of an error it already knows how to avoid.
  const documentSources = (sources ?? []).filter((s) => s.source_type === "documents");

  /**
   * Apply a change and re-validate, but only once errors are already on
   * screen. Validating before the first submit would shout at a half-typed
   * field; not re-validating after it leaves an error showing next to a
   * value the user has already fixed, which teaches people to ignore the
   * red text. Same rule as the pipeline builder's `revalidateField`.
   */
  const update = (patch: Partial<EvalSetDraft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    if (Object.keys(errors).length > 0) setErrors(validateEvalSetForm(next));
  };

  const setField = (i: number, patch: Partial<FieldDraft>) =>
    update({
      fields: draft.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)),
    });

  const save = async () => {
    const found = validateEvalSetForm(draft);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSaving(true);
    setErr(null);
    try {
      const created = await createEvalSet(toEvalSetPayload(draft));
      router.push(`/eval-sets/detail?id=${encodeURIComponent(created.id)}`);
    } catch (e) {
      setErr(humanizeError(e, { action: "create", entity: "eval set" }));
      setSaving(false);
    }
  };

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Eval sets", href: "/eval-sets" },
          { label: "New" },
        ]}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => router.back()} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={() => void save()} disabled={saving}>
              {saving ? "Creating…" : "Create eval set"}
            </Button>
          </>
        }
      />
      <PageHeader
        title="New eval set"
        lede="A labeled corpus and the fields to score. Add the labels next — from the document inspector, a consensus bootstrap, or a CSV import."
      />

      <div className="px-14 py-8 max-w-[860px] flex flex-col gap-6">
        {err && <InlineError title={err.title} message={err.message} detail={err.detail} />}

        <div className="grid grid-cols-2 gap-4">
          <Field label="Name" error={errors.name} hint="What this corpus is for.">
            <Input
              value={draft.name}
              onChange={(e) => update({ name: e.target.value })}
              placeholder="Invoice fields"
            />
          </Field>
          <Field
            label="Id"
            error={errors.id}
            hint="Optional — generated if you leave it blank."
          >
            <Input
              value={draft.id}
              onChange={(e) => update({ id: e.target.value })}
              placeholder="invoice_fields"
            />
          </Field>
        </div>

        <Field
          label="Documents source"
          error={errors.source_id}
          hint="The corpus. Labels are keyed by document hash, so only a documents source can be scored."
        >
          <Dropdown
            value={draft.source_id}
            onChange={(v) => update({ source_id: v })}
            placeholder={
              documentSources.length === 0
                ? "No documents sources yet — create one first"
                : "— pick a documents source —"
            }
            options={documentSources.map((s) => ({ value: s.id, label: s.id }))}
          />
        </Field>

        <Panel>
          <PanelHead label="Fields to score" count={draft.fields.length} />
          <div className="px-4 py-3 flex flex-col gap-3">
            <p className="text-[12.5px] text-muted">
              These names must match what your pipeline&apos;s{" "}
              <code className="font-mono">structure</code>{" "}step produces —
              scoring joins them by name. A name that doesn&apos;t match
              won&apos;t error; it scores zero on every document, which reads
              as a broken extractor.
            </p>

            {draft.fields.map((f, i) => (
              <div key={i} className="grid grid-cols-[1fr_130px_1fr_110px_auto] gap-2 items-start">
                <Input
                  value={f.name}
                  onChange={(e) => setField(i, { name: e.target.value })}
                  placeholder="total"
                />
                <Dropdown
                  value={f.type}
                  onChange={(v) => setField(i, { type: v })}
                  options={FIELD_TYPES.map((t) => ({ value: t, label: t }))}
                />
                <Input
                  value={f.description ?? ""}
                  onChange={(e) => setField(i, { description: e.target.value })}
                  placeholder="what this field is"
                />
                {/* Only numeric fields have a tolerance. Money is the common
                    case and exact match on it is the classic false failure:
                    1240.5 vs 1240.50. */}
                {f.type === "numeric" ? (
                  <Input
                    value={f.rel_tol ?? ""}
                    onChange={(e) => setField(i, { rel_tol: e.target.value })}
                    placeholder="rel_tol"
                  />
                ) : (
                  <span />
                )}
                <button
                  type="button"
                  className="text-[12px] text-subtle hover:text-[color:var(--red)] disabled:opacity-40 pt-2"
                  disabled={draft.fields.length === 1}
                  title={
                    draft.fields.length === 1
                      ? "An eval set needs at least one field"
                      : "Remove this field"
                  }
                  onClick={() =>
                    update({ fields: draft.fields.filter((_, j) => j !== i) })
                  }
                >
                  Remove
                </button>
              </div>
            ))}

            {errors.fields && (
              <p className="text-[12.5px] text-[color:var(--red)]">{errors.fields}</p>
            )}

            <div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => update({ fields: [...draft.fields, emptyField()] })}
              >
                + Add field
              </Button>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
