"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, PageHeader, Panel, Topbar } from "@/components/ui";
import { createSource, updateSource, type Source } from "@/lib/api";
import { SourceEditor } from "@/components/builder/sources/SourceEditor";

export function SourceForm({
  initial,
  mode,
}: {
  initial: Source;
  mode: "create" | "edit";
}) {
  const router = useRouter();
  const [source, setSource] = useState<Source>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const validate = (): string | null => {
    if (!source.id.trim()) return "Source id is required.";
    if (!/^[a-zA-Z0-9_-]+$/.test(source.id))
      return "Source id may only contain letters, numbers, '_' and '-'.";
    if (!source.table.trim()) return "Table name is required.";
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
        await createSource(source);
      } else {
        await updateSource(source.id, source);
      }
      router.push("/sources");
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
          { label: "Sources", href: "/sources" },
          { label: mode === "create" ? "New" : `Edit · ${initial.id}` },
        ]}
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={save}
              disabled={saving}
            >
              {saving ? "Saving…" : "Save source"}
            </Button>
          </>
        }
      />
      <PageHeader
        title={mode === "create" ? "New source" : `Editing ${initial.id}`}
        sub={mode === "edit" ? initial.id : undefined}
      />
      <div className="px-14 py-8 space-y-4">
        {err && (
          <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
            {err}
          </div>
        )}
        <Panel>
          <SourceEditor source={source} onChange={setSource} />
        </Panel>
      </div>
    </>
  );
}
