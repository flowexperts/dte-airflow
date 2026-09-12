"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { USE_CASES } from "@/lib/use-cases";

const SEEN_KEY = "dte-usecase-picked";

const remember = (value: string) => {
  try { localStorage.setItem(SEEN_KEY, value); } catch { /* storage blocked */ }
};

/** First-visit ask: "where will you use DTE?". Answering navigates to that
 *  use-case page; the answer (or a dismissal) is remembered so the overlay
 *  never interrupts twice. Landing also carries a static picker row, so this
 *  disappearing costs nothing. */
export function UseCasePicker() {
  const [open, setOpen] = useState(false);

  const dismiss = useCallback(() => {
    remember("browsing");
    setOpen(false);
  }, []);

  // Deferred a frame past hydration: the prerendered HTML has no overlay, so
  // opening it synchronously would be a state change mid-hydration.
  useEffect(() => {
    let seen = true;
    try { seen = Boolean(localStorage.getItem(SEEN_KEY)); } catch { /* stay closed */ }
    if (seen) return;
    const id = requestAnimationFrame(() => setOpen(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // Esc closes, and the overlay owns the scroll while it is up.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") dismiss(); };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, dismiss]);

  if (!open) return null;

  return (
    <div className="ucp-backdrop" role="dialog" aria-modal="true" aria-labelledby="ucp-title">
      <div className="ucp-card">
        <span className="section-eyebrow" id="ucp-title">Where will you use DTE?</span>
        <p className="ucp-sub">Pick the closest one — we&apos;ll show you that pipeline.</p>
        <div className="ucp-opts">
          {USE_CASES.map((u) => (
            <Link
              key={u.slug}
              className="ucp-opt"
              href={`/use-cases/${u.slug}/`}
              onClick={() => remember(u.slug)}
            >
              <span className="ucp-opt-dept">{u.dept}</span>
              <span className="ucp-opt-pick">{u.pick}</span>
            </Link>
          ))}
        </div>
        <button type="button" className="ucp-skip" onClick={dismiss}>
          Just browsing →
        </button>
      </div>
    </div>
  );
}

/** Same five links, inline on the landing page — for anyone who dismissed the
 *  overlay, and for crawlers, which never see it. */
export function UseCaseCards() {
  return (
    <div className="steps-grid">
      {USE_CASES.map((u) => (
        <Link key={u.slug} className="steps-card uc-card" href={`/use-cases/${u.slug}/`}>
          <span className="uc-card-dept">{u.dept}</span>
          <span className="steps-card-label">{u.pick}</span>
          <span className="steps-card-hint">{u.headline}</span>
        </Link>
      ))}
    </div>
  );
}
