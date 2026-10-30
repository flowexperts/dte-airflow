import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { Button, Dropdown, Field, Panel, PanelHead, Textarea } from "@/components/ui";
import { portalHost } from "@/components/ui/portal-host";
import {
  ApiError,
  getNotifications,
  listNotifiers,
  putNotifications,
  type NotifierInfo,
  type NotifyEvent,
  type PipelineNotification,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";

const EVENTS: { value: NotifyEvent; label: string }[] = [
  { value: "failure", label: "Failure" },
  { value: "retry", label: "Retry" },
  { value: "success", label: "Success" },
];

/** Constructor params that carry the message body — prefilled with the run
 *  summary DTE puts in the template context. */
const MESSAGE_PARAMS = new Set(["text", "message", "html_content", "body", "description"]);

const shortName = (path: string) => path.split(".").pop() ?? path;

/** `{code: "invalid_notification", index, message}` from the save. */
function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const raw = e.rawDetail as { message?: unknown; index?: unknown } | undefined;
    if (raw && typeof raw === "object" && "message" in raw) {
      const at = typeof raw.index === "number" ? `Notification ${raw.index + 1}: ` : "";
      return at + String(raw.message);
    }
    return e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

/** A pipeline's notifications (plan 070): any Airflow provider notifier, fired
 *  on its runs' events — manual and scheduled alike, so independent of the
 *  schedule. Every change is a pipeline revision. */
export function NotificationsPanel({ pipelineId }: { pipelineId: string }) {
  const { data: list, error, isLoading, mutate } = useSWR(
    ["pipeline-notifications", pipelineId],
    () => getNotifications(pipelineId),
  );
  const { can } = usePermissions();
  const canWrite = can("pipeline:write");
  // null = closed; -1 = adding; otherwise the index being edited.
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (next: PipelineNotification[]) => {
    const saved = await putNotifications(pipelineId, next);
    mutate(saved, { revalidate: false });
  };

  const remove = async (i: number) => {
    if (!list || !window.confirm(`Remove the ${shortName(list[i]!.notifier)} notification?`)) return;
    setBusy(true);
    try {
      await save(list.filter((_, j) => j !== i));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <PanelHead label="Notifications" />
      {isLoading && <div className="text-[12px] text-subtle px-3.5 py-4">Loading notifications…</div>}
      {error && <div className="text-[12px] text-red px-3.5 py-4">Couldn&apos;t load notifications.</div>}
      {list && list.length === 0 && (
        <div className="text-[12px] text-subtle px-3.5 py-4">
          No notifications — runs finish silently.
        </div>
      )}
      {list?.map((n, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto] gap-2.5 items-center px-3.5 py-2.5 border-t border-border first:border-t-0">
          <div className="min-w-0">
            <div className="font-mono text-[13px] text-text truncate" title={n.notifier}>
              {shortName(n.notifier)}
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-subtle">on {n.on.join(", ")}</div>
          </div>
          {canWrite && (
            <div className="flex items-center gap-1.5 shrink-0">
              <Button size="sm" onClick={() => setEditing(i)} disabled={busy}>Edit</Button>
              <Button size="sm" variant="ghost" onClick={() => remove(i)} disabled={busy}>Remove</Button>
            </div>
          )}
        </div>
      ))}
      {canWrite && list && (
        <div className="px-3.5 py-2.5 border-t border-border">
          <Button size="sm" onClick={() => setEditing(-1)}>+ Add notification</Button>
        </div>
      )}
      {editing !== null && list && (
        <NotificationForm
          initial={editing >= 0 ? list[editing] : undefined}
          onClose={() => setEditing(null)}
          onSave={async (n) => {
            await save(editing >= 0 ? list.map((x, j) => (j === editing ? n : x)) : [...list, n]);
            setEditing(null);
          }}
        />
      )}
    </Panel>
  );
}

function NotificationForm({
  initial,
  onClose,
  onSave,
}: {
  initial?: PipelineNotification | undefined;
  onClose: () => void;
  onSave: (n: PipelineNotification) => Promise<void>;
}) {
  const { data: notifiers } = useSWR<NotifierInfo[]>(["notifiers"], () => listNotifiers());
  const [notifier, setNotifier] = useState(initial?.notifier ?? "");
  const [events, setEvents] = useState<NotifyEvent[]>(initial?.on ?? ["failure"]);
  const [paramsText, setParamsText] = useState(() => JSON.stringify(initial?.params ?? {}, null, 2));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const info = notifiers?.find((n) => n.notifier === notifier);

  const pick = (path: string) => {
    setNotifier(path);
    // Prefill the new notifier's own args: required ones blank, the message
    // one pointing at DTE's run summary.
    const chosen = notifiers?.find((n) => n.notifier === path);
    const seed: Record<string, string> = {};
    for (const p of chosen?.params ?? []) {
      if (MESSAGE_PARAMS.has(p.name)) seed[p.name] = "{{ dte_message }}";
      else if (p.required) seed[p.name] = "";
    }
    setParamsText(JSON.stringify(seed, null, 2));
  };

  let params: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(paramsText || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) params = parsed as Record<string, unknown>;
  } catch {
    params = null;
  }
  const submittable = notifier !== "" && events.length > 0 && params !== null;

  const submit = async () => {
    if (!params) return;
    setBusy(true);
    setErr(null);
    try {
      await onSave({ notifier, params, on: events });
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!mounted) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[560px] max-h-[calc(100vh-3rem)] overflow-y-auto rounded-md border border-border bg-surface p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 text-sm font-medium">{initial ? "Edit notification" : "New notification"}</div>
        <div className="space-y-4">
          <Field label="Notifier" hint={info?.doc || "Every notifier your installed Airflow providers offer."}>
            <Dropdown<string>
              value={notifier}
              onChange={pick}
              placeholder={notifiers === undefined ? "Loading notifiers…" : notifiers.length === 0 ? "No notifier providers installed" : "— select a notifier —"}
              options={(notifiers ?? []).map((n) => ({ value: n.notifier, label: `${n.name} · ${n.notifier.split(".")[2] ?? ""}` }))}
            />
          </Field>

          <Field label="When" hint="Applies to manual and scheduled runs. Failure fires once, after the last retry.">
            <div className="flex items-center gap-4">
              {EVENTS.map((ev) => (
                <label key={ev.value} className="flex items-center gap-1.5 text-[13px]">
                  <input
                    type="checkbox"
                    checked={events.includes(ev.value)}
                    onChange={(e) =>
                      setEvents((cur) => (e.target.checked ? [...cur, ev.value] : cur.filter((x) => x !== ev.value)))
                    }
                  />
                  {ev.label}
                </label>
              ))}
            </div>
          </Field>

          <Field
            label="Parameters"
            hint={
              <>
                The notifier&apos;s own arguments, as JSON
                {info ? `: ${info.params.map((p) => p.name + (p.required ? "*" : "")).join(", ")}` : ""}.
                Templated ones can use {"{{ dte_message }}"} (pipeline, run, error) and {"{{ dte_event }}"}.
                Connection ids must exist in Airflow.
              </>
            }
            error={params === null ? "Not a JSON object." : undefined}
          >
            <Textarea rows={8} value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
          </Field>
        </div>

        {err && (
          <div className="mt-4 rounded border border-red/40 bg-red/10 p-2 font-mono text-[11px] text-red">{err}</div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" size="sm" disabled={busy || !submittable} onClick={submit}>
            {busy ? "Saving…" : initial ? "Save changes" : "Add notification"}
          </Button>
        </div>
      </div>
    </div>,
    portalHost(),
  );
}
