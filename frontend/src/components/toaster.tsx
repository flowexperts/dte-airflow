"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Toast = { id: number; message: string; kind: "info" | "error" };

type Ctx = { push: (message: string, kind?: Toast["kind"]) => void };

const ToastCtx = createContext<Ctx | null>(null);

export function useToast(): Ctx {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast used outside <Toaster />");
  return ctx;
}

export function Toaster({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, kind: Toast["kind"] = "info") => {
    setToasts((prev) => [...prev, { id: Date.now() + Math.random(), message, kind }]);
  }, []);

  useEffect(() => {
    if (!toasts.length) return;
    const t = setTimeout(() => setToasts((prev) => prev.slice(1)), 4000);
    return () => clearTimeout(t);
  }, [toasts]);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={
              "rounded-md px-4 py-2 text-sm shadow-lg border " +
              (t.kind === "error"
                ? "bg-red-950/90 border-red-800 text-red-100"
                : "bg-surface border-border text-fg")
            }
            role={t.kind === "error" ? "alert" : "status"}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
