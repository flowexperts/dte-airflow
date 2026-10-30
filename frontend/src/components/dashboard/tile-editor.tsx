/**
 * Editing one tile (plan 064).
 *
 * Field options come from the tile's own pipeline **preview**, not from a
 * schema endpoint: the preview call is already in flight for the chart
 * beside it, so the columns are free. It also means the picker offers the
 * columns that actually come out the end of the pipeline — after every
 * rename and select — which a source schema would not.
 */
import useSWR from "swr";
import {
  Button,
  Dropdown,
  Field,
  Input,
  Panel,
  Segmented,
  type DropdownOption,
} from "@/components/ui";
import {
  listPipelines,
  previewPipeline,
  type ChartKind,
  type DashboardTile,
  type Pipeline,
  type TileHeight,
  type TileWidth,
} from "@/lib/api";
import { visibleColumns } from "@/lib/system-columns";

const KINDS: ChartKind[] = ["bar", "line", "area", "pie", "number", "table"];

/** Kinds where a category axis is meaningful. `number` reads one value and
 *  `table` prints the rows, so neither takes an x. */
const HAS_X: ChartKind[] = ["bar", "line", "area", "pie"];

export function TileEditor({
  tile,
  onChange,
  onRemove,
  onMove,
}: {
  tile: DashboardTile;
  onChange: (next: DashboardTile) => void;
  onRemove: () => void;
  onMove: (delta: -1 | 1) => void;
}) {
  const { data: pipelines } = useSWR<Pipeline[]>("pipelines-for-tiles", () => listPipelines(200));
  const { data: preview } = useSWR(
    tile.pipeline_id ? ["tile-columns", tile.pipeline_id] : null,
    // One row is enough to learn the column names, and it keeps the editor
    // from re-running a heavy pipeline at full limit on every keystroke.
    () => previewPipeline(tile.pipeline_id, 1),
  );

  const columns = visibleColumns(Object.keys(preview?.rows?.[0] ?? {}));
  const colOptions: DropdownOption<string>[] = columns.map((c) => ({ value: c, label: c }));

  const setChart = (patch: Partial<DashboardTile["chart"]>) =>
    onChange({ ...tile, chart: { ...tile.chart, ...patch } });

  const kind = tile.chart.kind;

  return (
    <Panel>
      <div className="p-3 space-y-3">
        <div className="flex items-center gap-2">
          <Input
            value={tile.title}
            onChange={(e) => onChange({ ...tile, title: e.target.value })}
            placeholder="Revenue by region"
          />
          <Button variant="ghost" size="sm" onClick={() => onMove(-1)} title="Move up">
            ↑
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onMove(1)} title="Move down">
            ↓
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove} title="Remove tile">
            ×
          </Button>
        </div>

        <Field label="Pipeline" hint="its preview rows are what this tile draws">
          <Dropdown<string>
            value={tile.pipeline_id}
            onChange={(v) => onChange({ ...tile, pipeline_id: v })}
            options={(pipelines ?? []).map((p) => ({
              value: p.id,
              label: p.name,
              meta: p.pipeline_type ?? "transform",
            }))}
            placeholder="— pick a pipeline —"
          />
        </Field>

        <Field label="Chart">
          <Segmented<ChartKind>
            options={KINDS.map((k) => ({ value: k, label: k }))}
            value={kind}
            onChange={(k) =>
              // `number` takes exactly one measure and no axis; the backend
              // enforces it, so narrow here rather than letting a save 422
              // on state the editor no longer shows.
              setChart(
                k === "number"
                  ? { kind: k, x: null, series: null, y: tile.chart.y.slice(0, 1) }
                  : { kind: k },
              )
            }
          />
        </Field>

        {HAS_X.includes(kind) && (
          <Field label="Category axis" hint="x — one bar / point per distinct value">
            <Dropdown<string>
              value={tile.chart.x ?? ""}
              onChange={(v) => setChart({ x: v })}
              options={colOptions}
              placeholder={columns.length ? "— pick a column —" : "run the pipeline first"}
            />
          </Field>
        )}

        {kind !== "table" && (
          <Field
            label="Value"
            hint={
              kind === "number"
                ? "the single figure to show"
                : "the measure to plot — aggregate it in the pipeline, not here"
            }
          >
            <Dropdown<string>
              value={tile.chart.y[0] ?? ""}
              onChange={(v) => setChart({ y: [v] })}
              options={colOptions}
              placeholder={columns.length ? "— pick a column —" : "run the pipeline first"}
            />
          </Field>
        )}

        {HAS_X.includes(kind) && kind !== "pie" && (
          <Field label="Split by" hint="optional — one coloured series per distinct value">
            <Dropdown<string>
              value={tile.chart.series ?? ""}
              onChange={(v) => setChart({ series: v || null })}
              options={[{ value: "", label: "— none —" }, ...colOptions]}
              placeholder="— none —"
            />
          </Field>
        )}

        <div className="flex items-center gap-3">
          <Field label="Width">
            <Segmented<string>
              options={[
                { value: "4", label: "⅓" },
                { value: "6", label: "½" },
                { value: "12", label: "Full" },
              ]}
              value={String(tile.width)}
              onChange={(v) => onChange({ ...tile, width: Number(v) as TileWidth })}
            />
          </Field>
          <Field label="Height">
            <Segmented<TileHeight>
              options={[
                { value: "s", label: "S" },
                { value: "m", label: "M" },
                { value: "l", label: "L" },
              ]}
              value={tile.height}
              onChange={(v) => onChange({ ...tile, height: v })}
            />
          </Field>
        </div>
      </div>
    </Panel>
  );
}
