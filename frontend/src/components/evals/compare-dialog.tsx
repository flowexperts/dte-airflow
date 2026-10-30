import { useEffect } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "@/components/ui/portal-host";
import { useMounted } from "@/components/ui/use-mounted";
import type { Pipeline } from "@/lib/api";
import { MatrixPanel } from "./matrix-panel";

/**
 * The comparison launcher, reached from the Compare button in the nav bar
 * rather than sitting permanently open above the steps.
 *
 * `MatrixPanel` itself is unchanged — same estimate/run flow, same
 * pipeline-is-the-source-of-truth editing via `onChange`. Only where it
 * renders moved: a modal you open on demand instead of a block every eval
 * pipeline always showed, whether or not you came here to compare configs.
 */
export function CompareDialog({
  pipeline,
  onChange,
  readOnly,
  open,
  onClose,
}: {
  pipeline: Pipeline;
  onChange: (matrix: Record<string, string[]> | null) => void;
  readOnly?: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const mounted = useMounted();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-8"
      onClick={onClose}
    >
      <div className="relative w-full max-w-[640px] mt-8" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute -top-2 -right-2 z-10 w-6 h-6 rounded-full border border-border bg-surface text-subtle hover:text-red text-[13px] leading-none flex items-center justify-center shadow-sm"
        >
          ×
        </button>
        <MatrixPanel pipeline={pipeline} onChange={onChange} readOnly={readOnly ?? false} />
      </div>
    </div>,
    portalHost(),
  );
}
