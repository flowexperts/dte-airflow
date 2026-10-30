import { useState } from "react";
import { Button, Dropdown, Panel, PanelHead } from "@/components/ui";
import { PromoteForm } from "./promote-button";
import { usePermissions } from "@/lib/use-permissions";
import { cellLabel } from "@/lib/comparison-cell";
import { shippableCells, hasShippableCell } from "@/lib/comparison-shippable";
import type { ComparisonCell } from "@/lib/api";

/**
 * Ship the config you picked, from the page where you picked it.
 *
 * Plan 053 made the comparison reachable and readable and gave it no exit:
 * `promote` was rendered only on the leaderboard, which ranks *scored* runs
 * and so needs labels the comparison deliberately does not require. The
 * documented way out — accept labels, then leaderboard, then promote — is
 * additionally refused whenever every config shares a provider, which is
 * exactly what a model or prompt sweep produces.
 *
 * One control, not one per cell. The promote form does not fit a 220px card,
 * and more importantly Promote is the page's exit rather than a property of
 * any one cell: by the time you reach for it the decision is made, and the
 * UI's job is to accept it, not to re-offer it N ways.
 *
 * Nothing is preselected. Without labels this page computes no ranking, and
 * with them it computes ties rather than winners — so a default would assert
 * something neither state supports. The `best`/`tied` pills on the cards
 * already say everything the data supports.
 */
export function PromoteFromComparison({
  evalSetId,
  cells,
}: {
  evalSetId: string;
  cells: ComparisonCell[];
}) {
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  const [pipelineId, setPipelineId] = useState("");

  if (!can("eval:write")) return null;

  const options = shippableCells(cells);
  const anyShippable = hasShippableCell(cells);

  if (!open) {
    return (
      <Button
        variant="default"
        size="sm"
        disabled={!anyShippable}
        onClick={() => setOpen(true)}
        title={
          anyShippable
            ? "Copy one of these configs into a transform pipeline that writes real output"
            : "No config here finished with values to ship"
        }
      >
        Ship a config…
      </Button>
    );
  }

  return (
    <div className="w-full mt-2">
      <Panel>
        <PanelHead label="Ship a config" />
        <div className="px-4 py-3 flex flex-col gap-2">
          <Dropdown
            value={pipelineId}
            onChange={setPipelineId}
            placeholder="— which config? —"
            options={options.map((o) => ({
              value: o.cell.pipeline_id,
              /* Excluded cells stay in the list with the reason attached.
                 A silently missing option reads as a bug; "every row
                 errored" is the most useful thing this page can say. */
              label: o.shippable ? cellLabel(o.cell) : `${cellLabel(o.cell)} — ${o.reason}`,
              disabled: !o.shippable,
            }))}
          />
          <PromoteForm
            evalSetId={evalSetId}
            pipelineId={pipelineId}
            onDone={() => {
              setOpen(false);
              setPipelineId("");
            }}
            onCancel={() => setOpen(false)}
          />
        </div>
      </Panel>
    </div>
  );
}
