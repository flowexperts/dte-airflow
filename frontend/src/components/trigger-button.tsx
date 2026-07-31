"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import type { PipelineParam } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { TriggerModal } from "@/components/trigger-modal";

export function TriggerButton({
  pipelineId,
  params,
}: {
  pipelineId: string;
  params?: PipelineParam[] | undefined;
}) {
  const [open, setOpen] = useState(false);
  const { can } = usePermissions();
  if (!can("pipeline:trigger")) return null;

  return (
    <>
      <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
        Trigger run
      </Button>
      <TriggerModal
        pipelineId={pipelineId}
        params={params}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}
