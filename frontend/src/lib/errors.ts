import { ApiError, isPipelineGateError } from "./api";

export type ErrorKind =
  | "network"
  | "validation"
  | "conflict"
  | "not_found"
  | "permission"
  | "auth"
  | "gate"
  | "server"
  | "unknown";

export interface HumanError {
  title: string;
  message: string;
  detail?: string | undefined;
  kind: ErrorKind;
}

export interface HumanCtx {
  /** Verb: "delete", "save", "start", "load". Used in the title. */
  action?: string;
  /** Entity noun: "source", "connection", "pipeline". */
  entity?: string;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Format a Pydantic-style location array as a dotted path readers can scan. */
function formatLoc(loc: unknown[]): string {
  return loc
    .filter((p) => p !== "body")
    .map((p) => (typeof p === "number" ? `[${p}]` : String(p)))
    .join(".")
    .replace(/\.\[/g, "[");
}

/** Turn one Pydantic error entry into a plain-English sentence. */
function pydanticEntry(e: { loc?: unknown; msg?: unknown; type?: unknown }): string {
  const loc = Array.isArray(e.loc) ? formatLoc(e.loc) : "";
  const msg = typeof e.msg === "string" ? e.msg : "invalid";
  const type = typeof e.type === "string" ? e.type : "";
  if (type === "missing" || /field required/i.test(msg)) {
    return loc ? `${loc} is required` : "A required field is missing";
  }
  if (type === "value_error" && loc) return `${loc}: ${msg}`;
  return loc ? `${loc}: ${msg}` : msg;
}

function parsePydantic(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const parts = detail
    .filter((e): e is Record<string, unknown> => !!e && typeof e === "object")
    .map((e) => pydanticEntry(e as { loc?: unknown; msg?: unknown; type?: unknown }))
    .filter(Boolean);
  if (!parts.length) return null;
  return parts.slice(0, 3).join("; ") + (parts.length > 3 ? `; +${parts.length - 3} more` : "");
}

/** Try to rewrite a DuckDB / compiler string into something a non-engineer can read. */
function humanizeCompilerString(raw: string): string | null {
  const s = raw.trim();
  const firstLine = (m: string | undefined) => (m ?? "").split("\n")[0] ?? "";
  const notFound =
    s.match(/column\s+"?([^"\s]+)"?\s+not\s+found/i) ||
    s.match(/Referenced column\s+"?([^"\s]+)"?\s+not found/i);
  if (notFound) return `Column "${notFound[1]}" isn't in the data at this step.`;
  const binder = s.match(/Binder Error:\s*(.+)/i);
  if (binder) return `The query couldn't be built: ${firstLine(binder[1])}`;
  const parser = s.match(/Parser Error:\s*(.+)/i);
  if (parser) return `Invalid SQL: ${firstLine(parser[1])}`;
  const conv = s.match(/Conversion Error:\s*(.+)/i);
  if (conv) return `A value couldn't be converted: ${firstLine(conv[1])}`;
  const io = s.match(/IO Error:\s*(.+)/i);
  if (io) return `Couldn't read the source file: ${firstLine(io[1])}`;
  return null;
}

function shortDetail(raw: unknown): string | undefined {
  if (raw == null) return undefined;
  if (typeof raw === "string") return raw.length > 800 ? raw.slice(0, 800) + "…" : raw;
  try {
    const s = JSON.stringify(raw, null, 2);
    return s.length > 1200 ? s.slice(0, 1200) + "…" : s;
  } catch {
    return String(raw);
  }
}

function describeReferencedBy(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return null;
  const refs = (raw as { referenced_by?: unknown }).referenced_by;
  if (!refs) return null;
  // Two shapes seen in the codebase:
  //   sources / destinations delete → { referenced_by: [id, ...] }
  //   connections delete → { referenced_by: { sources: [...], destinations: [...] } }
  if (Array.isArray(refs)) {
    const n = refs.length;
    const preview = refs.slice(0, 3).map(String).join(", ");
    return `${n} pipeline${n === 1 ? "" : "s"} still use it${preview ? ` (${preview}${n > 3 ? ", …" : ""})` : ""}.`;
  }
  if (typeof refs === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(refs as Record<string, unknown>)) {
      if (Array.isArray(v) && v.length) {
        parts.push(`${v.length} ${k}`);
      }
    }
    if (parts.length) return `Still in use by ${parts.join(" and ")}.`;
  }
  return null;
}

/** Central humanizer. Never throws; always returns something renderable. */
export function humanizeError(err: unknown, ctx: HumanCtx = {}): HumanError {
  const entity = ctx.entity ?? "item";
  const action = ctx.action ?? "complete that action";

  if (err instanceof ApiError) {
    const detail = shortDetail(err.rawDetail);

    // Pipeline gate errors — the builder renders these itself; give a generic
    // toast copy when a caller sends one through here anyway.
    if (isPipelineGateError(err.rawDetail)) {
      return {
        title: "This pipeline can't run on the selected engine",
        message: "Switch the engine or adjust the incompatible source/destination.",
        detail,
        kind: "gate",
      };
    }

    if (err.status === 0) {
      return {
        title: "Can't reach the server",
        message: "Check your connection or make sure the backend is running.",
        detail,
        kind: "network",
      };
    }
    if (err.status === 401) {
      return {
        title: "Session expired",
        message: "Sign in again to continue.",
        detail,
        kind: "auth",
      };
    }
    if (err.status === 403) {
      return {
        title: "You don't have access",
        message: `You're not allowed to ${action} this ${entity}.`,
        detail,
        kind: "permission",
      };
    }
    if (err.status === 404) {
      return {
        title: `${cap(entity)} not found`,
        message: `That ${entity} no longer exists — it may have been deleted.`,
        detail,
        kind: "not_found",
      };
    }
    if (err.status === 409) {
      const ref = describeReferencedBy(err.rawDetail);
      return {
        title: `Can't ${action} this ${entity}`,
        message: ref ?? "It conflicts with existing data.",
        detail,
        kind: "conflict",
      };
    }
    if (err.status === 422) {
      const parsed = parsePydantic(err.rawDetail) ?? (typeof err.rawDetail === "string" ? err.rawDetail : null);
      return {
        title: "Some fields need attention",
        message: parsed ?? "Check the highlighted fields and try again.",
        detail,
        kind: "validation",
      };
    }
    if (err.status >= 500) {
      return {
        title: "Something went wrong on our side",
        message: "Try again in a moment. If it keeps happening, share the details below with the team.",
        detail,
        kind: "server",
      };
    }
    // Other 4xx
    return {
      title: `Couldn't ${action}`,
      message: typeof err.detail === "string" && err.detail ? err.detail : "The request was rejected.",
      detail,
      kind: "unknown",
    };
  }

  // Network-level fetch failure surfaces as TypeError("Failed to fetch")
  if (err instanceof TypeError && /fetch/i.test(err.message)) {
    return {
      title: "Can't reach the server",
      message: "Check your connection or make sure the backend is running.",
      detail: err.message,
      kind: "network",
    };
  }

  if (err instanceof Error) {
    return {
      title: `Couldn't ${action}`,
      message: err.message || "Something unexpected happened.",
      kind: "unknown",
    };
  }

  return {
    title: "Unexpected error",
    message: "Something unexpected happened. Try again.",
    detail: shortDetail(err),
    kind: "unknown",
  };
}

/**
 * Best-effort humanizer for compiler/executor error *strings* (as returned in
 * `Run.error` and `PreviewResponse.error`). Wraps `humanizeError` output shape
 * so callers can render both channels with the same panel.
 */
export function humanizeCompilerError(raw: string | null | undefined): HumanError | null {
  if (!raw) return null;
  const rewritten = humanizeCompilerString(raw);
  if (rewritten) {
    return {
      title: "The pipeline couldn't run",
      message: rewritten,
      detail: raw,
      kind: "validation",
    };
  }
  return {
    title: "The pipeline couldn't run",
    message: "The engine reported an error while running this pipeline.",
    detail: raw,
    kind: "server",
  };
}
