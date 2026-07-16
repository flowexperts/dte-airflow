"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHead,
  Dropdown,
  Topbar,
} from "@/components/ui";
import {
  createConnection,
  updateConnection,
  type Connection,
  type ConnectionType,
} from "@/lib/api";
import { CONNECTION_KINDS, emptyCredentials } from "@/components/connections/types";
import { CredentialFields } from "@/components/connections/CredentialFields";

export function ConnectionForm({
  initial,
  mode,
}: {
  initial: Connection;
  mode: "create" | "edit";
}) {
  const router = useRouter();
  const [connection, setConnection] = useState<Connection>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const setKind = (k: ConnectionType) => {
    setConnection({
      ...connection,
      connection_type: k,
      credentials: emptyCredentials(k),
    });
  };

  const validate = (): string | null => {
    if (!connection.id.trim()) return "Connection id is required.";
    if (!/^[a-zA-Z0-9_-]+$/.test(connection.id))
      return "Connection id may only contain letters, numbers, '_' and '-'.";
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) { setErr(problem); return; }
    setSaving(true);
    setErr(null);
    try {
      if (mode === "create") {
        await createConnection(connection);
      } else {
        await updateConnection(connection.id, connection);
      }
      router.push("/connections");
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
          { label: "Connections", href: "/connections" },
          { label: mode === "create" ? "New" : `Edit · ${initial.id}` },
        ]}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => router.back()} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save connection"}
            </Button>
          </>
        }
      />
      <PageHeader
        title={mode === "create" ? "New connection" : `Editing ${initial.id}`}
        sub={mode === "edit" ? initial.id : undefined}
      />
      <div className="px-14 py-8 space-y-4">
        {err && (
          <div className="p-3 border border-red rounded bg-code-bg text-red font-mono text-[12.5px]">
            {err}
          </div>
        )}
        <Panel>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Connection id" hint="stable identifier; can't change after create">
                <Input
                  value={connection.id}
                  onChange={(e) => setConnection({ ...connection, id: e.target.value })}
                  disabled={mode === "edit"}
                />
              </Field>
              <Field label="Type">
                <Dropdown<ConnectionType>
                  value={connection.connection_type}
                  onChange={setKind}
                  options={CONNECTION_KINDS}
                />
              </Field>
            </div>
          </div>
        </Panel>
        <Panel>
          <PanelHead label="Credentials" />
          <CredentialFields
            kind={connection.connection_type}
            credentials={connection.credentials}
            onChange={(credentials) => setConnection({ ...connection, credentials })}
          />
        </Panel>
        {mode === "edit" && (
          <div className="text-xs text-subtle font-mono">
            Leave credentials blank to keep the existing set.
          </div>
        )}
      </div>
    </>
  );
}
