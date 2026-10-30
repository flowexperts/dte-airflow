import { createContext, useCallback, useContext, useEffect, useState } from "react";

type ToastKind = "info" | "success" | "error";

interface RichToast {
  id: number;
  kind: ToastKind;
  title: string;
  message?: string | undefined;
  detail?: string | undefined;
}

interface Ctx {
  /** Legacy single-string API — kept for existing call sites. */
  push: (message: string, kind?: "info" | "error") => void;
  /** Rich API used by humanized error handlers. */
  error: (t: { title: string; message?: string | undefined; detail?: string | undefined }) => void;
  success: (t: { title: string; message?: string | undefined }) => void;
}

const ToastCtx = createContext<Ctx | null>(null);

export function useToast(): Ctx {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast used outside <Toaster />");
  return ctx;
}

const AUTO_DISMISS_MS: Record<ToastKind, number> = {
  info: 4000,
  success: 5000,
  error: 9000,
};

export function Toaster({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<RichToast[]>([]);

  const add = useCallback((t: Omit<RichToast, "id">) => {
    setToasts((prev) => [...prev, { ...t, id: Date.now() + Math.random() }]);
  }, []);

  const push = useCallback(
    (message: string, kind: "info" | "error" = "info") => {
      add({ kind, title: message });
    },
    [add],
  );

  const error = useCallback(
    (t: { title: string; message?: string | undefined; detail?: string | undefined }) =>
      add({ kind: "error", ...t }),
    [add],
  );

  const success = useCallback(
    (t: { title: string; message?: string | undefined }) => add({ kind: "success", ...t }),
    [add],
  );

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastCtx.Provider value={{ push, error, success }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-[380px]">
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function ToastCard({ toast, onDismiss }: { toast: RichToast; onDismiss: () => void }) {
  const [showDetail, setShowDetail] = useState(false);

  useEffect(() => {
    const ms = AUTO_DISMISS_MS[toast.kind];
    const timer = window.setTimeout(onDismiss, ms);
    return () => window.clearTimeout(timer);
  }, [toast.kind, onDismiss]);

  const palette =
    toast.kind === "error"
      ? "border-red/40 bg-code-bg"
      : toast.kind === "success"
        ? "border-accent/40 bg-surface"
        : "border-border bg-surface";
  const titleTone = toast.kind === "error" ? "text-red" : "text-text";

  return (
    <div
      role={toast.kind === "error" ? "alert" : "status"}
      className={`rounded-md border shadow-lg p-3 text-[13px] ${palette}`}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className={`font-medium ${titleTone}`}>{toast.title}</div>
          {toast.message && <div className="mt-0.5 text-[12.5px] text-muted">{toast.message}</div>}
          {toast.detail && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowDetail((v) => !v)}
                className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text"
              >
                {showDetail ? "Hide details" : "Show details"}
              </button>
              {showDetail && (
                <pre className="mt-1.5 font-mono text-[11px] text-subtle whitespace-pre-wrap break-words max-h-40 overflow-auto">
                  {toast.detail}
                </pre>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="text-subtle hover:text-text text-lg leading-none -mr-1 -mt-1 px-1"
        >
          ×
        </button>
      </div>
    </div>
  );
}
