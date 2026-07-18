"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import { triggerPipeline } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";

export function TriggerButton({ pipelineId }: { pipelineId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { can } = usePermissions();
  if (!can("pipeline:trigger")) return null;

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { run_id } = await triggerPipeline(pipelineId);
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {err && (
        <span className="font-mono text-[11px] text-red">{err}</span>
      )}
      <Button variant="primary" size="sm" disabled={busy} onClick={run}>
        {busy ? "Starting…" : "Trigger run"}
      </Button>
    </div>
  );
}
