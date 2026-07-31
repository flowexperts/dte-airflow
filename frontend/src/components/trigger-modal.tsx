"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import { triggerPipeline, type ParamType, type PipelineParam } from "@/lib/api";

/** Client-side validation mirror of `dte.compiler.interpolate.coerce_param_value`.
 *  Returns null on success, or a message. Server is source of truth — this
 *  only exists to disable Submit before a doomed round-trip. */
function validate(value: string, type: ParamType): string | null {
  if (value === "") return null; // caller handles required separately
  switch (type) {
    case "string":
      return null;
    case "int":
      return /^-?\d+$/.test(value) ? null : "not an integer";
    case "float":
      return !Number.isNaN(Number(value)) ? null : "not a number";
    case "boolean":
      return ["true", "false", "1", "0", "yes", "no"].includes(value.toLowerCase())
        ? null
        : "expected true/false";
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(value) ? null : "expected YYYY-MM-DD";
    case "timestamp":
      return !Number.isNaN(Date.parse(value)) ? null : "expected ISO timestamp";
  }
}

function inputTypeFor(t: ParamType): string {
  switch (t) {
    case "int":
    case "float":
      return "number";
    case "date":
      return "date";
    case "timestamp":
      return "datetime-local";
    default:
      return "text";
  }
}

/** Typed trigger dialog. Renders one input per declared `PipelineParam`. */
export function TriggerModal({
  pipelineId,
  params,
  open,
  onClose,
}: {
  pipelineId: string;
  params: PipelineParam[] | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const declared = params ?? [];
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const p of declared) seed[p.name] = "";
    return seed;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const fieldErrors: Record<string, string | null> = {};
  for (const p of declared) {
    const raw = values[p.name] ?? "";
    const isRequired = p.required !== false && (p.default == null || p.default === "");
    if (raw === "" && isRequired) {
      fieldErrors[p.name] = "required";
    } else {
      fieldErrors[p.name] = validate(raw, p.type);
    }
  }
  const submittable = declared.every((p) => !fieldErrors[p.name]);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const payload: Record<string, string> = {};
      for (const p of declared) {
        const raw = values[p.name] ?? "";
        // Omit empty optional params so the server applies the declared default.
        if (raw === "" && (p.required === false || (p.default ?? "") !== "")) continue;
        payload[p.name] = raw;
      }
      const { run_id } = await triggerPipeline(pipelineId, payload);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-[520px] rounded-md border border-border bg-surface p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 text-sm font-medium">Trigger run</div>
        {declared.length === 0 ? (
          <p className="mb-4 text-xs text-muted">
            Run <span className="font-mono">{pipelineId}</span> now?
          </p>
        ) : (
          <div className="space-y-3">
            {declared.map((p) => {
              const err = fieldErrors[p.name];
              const showErr = err && err !== "required";
              const isRequired = p.required !== false;
              return (
                <div key={p.name} className="grid grid-cols-[130px_1fr] gap-2 items-start">
                  <div className="pt-1.5 text-[12px] text-muted font-mono">
                    <span className="text-text">{p.name}</span>
                    {isRequired && <span className="text-red">*</span>}
                    <div className="text-[10.5px] text-subtle">{p.type}</div>
                  </div>
                  <div>
                    {p.type === "boolean" ? (
                      <div className="inline-flex border border-border rounded-[var(--radius)] bg-bg p-0.5">
                        {["true", "false"].map((v) => (
                          <button
                            key={v}
                            type="button"
                            onClick={() => setValues((s) => ({ ...s, [p.name]: v }))}
                            className={
                              (values[p.name] === v
                                ? "bg-[color:var(--accent-tint)] text-accent"
                                : "text-muted hover:text-text") +
                              " px-3 py-1 text-[12.5px] rounded-[3px]"
                            }
                          >
                            {v}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <input
                        type={inputTypeFor(p.type)}
                        value={values[p.name] ?? ""}
                        onChange={(e) =>
                          setValues((s) => ({ ...s, [p.name]: e.target.value }))
                        }
                        placeholder={p.default ?? ""}
                        className="w-full bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] focus:outline-none focus:border-accent font-mono"
                      />
                    )}
                    {p.description && (
                      <div className="mt-0.5 text-[10.5px] text-subtle">
                        {p.description}
                      </div>
                    )}
                    {showErr && (
                      <div className="mt-0.5 text-[10.5px] text-red">{err}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {err && (
          <div className="mt-3 rounded border border-red/40 bg-red/10 p-2 font-mono text-[11px] text-red">
            {err}
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={busy || !submittable}
            onClick={run}
          >
            {busy ? "Starting…" : "Trigger"}
          </Button>
        </div>
      </div>
    </div>
  );
}
