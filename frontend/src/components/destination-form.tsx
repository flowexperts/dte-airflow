"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Field,
  Input,
  PageHeader,
  Panel,
  Topbar,
} from "@/components/ui";
import {
  createDestination,
  updateDestination,
  isJsonFileOutput,
  type Destination,
} from "@/lib/api";
import { OutputPanel } from "@/components/builder/OutputPanel";

export function DestinationForm({
  initial,
  mode,
}: {
  initial: Destination;
  mode: "create" | "edit";
}) {
  const router = useRouter();
  const [destination, setDestination] = useState<Destination>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const validate = (): string | null => {
    if (!destination.id.trim()) return "Destination id is required.";
    if (!/^[a-zA-Z0-9_-]+$/.test(destination.id))
      return "Destination id may only contain letters, numbers, '_' and '-'.";
    if (isJsonFileOutput(destination.config) && !destination.config.path?.trim()) {
      return "Output path is required.";
    }
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) {
      setErr(problem);
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      if (mode === "create") {
        await createDestination(destination);
      } else {
        await updateDestination(destination.id, destination);
      }
      router.push("/destinations");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Destinations", href: "/destinations" },
          { label: mode === "create" ? "New" : `Edit · ${initial.id}` },
        ]}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => router.back()} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save destination"}
            </Button>
          </>
        }
      />
      <PageHeader
        title={mode === "create" ? "New destination" : `Editing ${initial.id}`}
        sub={mode === "edit" ? initial.id : undefined}
      />
      <div className="px-14 py-8 space-y-4">
        {err && (
          <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
            {err}
          </div>
        )}
        <Panel>
          <div className="p-4">
            <Field label="Destination id" hint="stable identifier; can't change after create">
              <Input
                value={destination.id}
                onChange={(e) => setDestination({ ...destination, id: e.target.value })}
                disabled={mode === "edit"}
              />
            </Field>
          </div>
        </Panel>
        {isJsonFileOutput(destination.config) ? (
          <OutputPanel
            output={destination.config}
            onChange={(cfg) => setDestination({ ...destination, config: cfg })}
          />
        ) : (
          <div className="border border-border rounded p-4 text-sm text-subtle bg-surface">
            {destination.config.type} destinations aren&apos;t editable in the UI yet.
          </div>
        )}
      </div>
    </>
  );
}
