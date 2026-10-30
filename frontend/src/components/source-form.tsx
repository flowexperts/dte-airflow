import { useState } from "react";
import { useRouter } from "@/lib/nav";
import { Button, InlineError, PageHeader, Panel, Topbar } from "@/components/ui";
import { createSource, updateSource, type Source } from "@/lib/api";
import { SourceEditor } from "@/components/builder/sources/SourceEditor";
import { SchemaProvider } from "@/components/builder/schema-context";
import { humanizeError, type HumanError } from "@/lib/errors";
import { validateSource } from "@/lib/source-validate";

export function SourceForm({ initial, mode }: { initial: Source; mode: "create" | "edit" }) {
  const router = useRouter();
  const [source, setSource] = useState<Source>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<HumanError | null>(null);

  const save = async () => {
    const problem = validateSource(source, mode);
    if (problem) {
      setErr({ title: "Check your input", message: problem, kind: "validation" });
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
      setErr(humanizeError(e, { action: "save", entity: "source" }));
      setSaving(false);
    }
  };

  return (
    <SchemaProvider>
      <Topbar
        crumbs={[
          { label: "Admin" },
          { label: "Sources", href: "/sources" },
          { label: mode === "create" ? "New" : `Edit · ${initial.id}` },
        ]}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => router.back()} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={saving}>
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
        {err && <InlineError title={err.title} message={err.message} detail={err.detail} />}
        <Panel>
          <SourceEditor source={source} onChange={setSource} />
        </Panel>
      </div>
    </SchemaProvider>
  );
}
