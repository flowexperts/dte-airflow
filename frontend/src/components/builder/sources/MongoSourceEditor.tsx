import { Field, Input } from "@/components/ui";

interface Config {
  database?: string;
  collection?: string;
  [k: string]: unknown;
}

export function MongoSourceEditor({
  config,
  onChange,
}: {
  config: Config;
  onChange: (next: Config) => void;
}) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Database">
          <Input
            value={config.database ?? ""}
            onChange={(e) => onChange({ ...config, database: e.target.value })}
            placeholder="app"
          />
        </Field>
        <Field label="Collection">
          <Input
            value={config.collection ?? ""}
            onChange={(e) => onChange({ ...config, collection: e.target.value })}
            placeholder="orders"
          />
        </Field>
      </div>
    </div>
  );
}
