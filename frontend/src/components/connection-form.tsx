"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Field,
  InlineError,
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
import { humanizeError, type HumanError } from "@/lib/errors";

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
  const [err, setErr] = useState<HumanError | null>(null);

  const setKind = (k: ConnectionType) => {
    setConnection({
      ...connection,
      connection_type: k,
      credentials: emptyCredentials(k),
    });
  };

  const validate = (): string | null => {
    const name = (connection.name ?? "").trim();
    if (!name) return "Connection name is required.";
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) {
      setErr({ title: "Check your input", message: problem, kind: "validation" });
      return;
    }
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
      setErr(humanizeError(e, { action: "save", entity: "connection" }));
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
        title={mode === "create" ? "New connection" : `Editing ${initial.name ?? initial.id}`}
        sub={mode === "edit" ? initial.name ?? initial.id : undefined}
      />
      <div className="px-14 py-8 space-y-4">
        {err && <InlineError title={err.title} message={err.message} detail={err.detail} />}
        <Panel>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name" hint="editable; must be unique">
                <Input
                  value={connection.name ?? ""}
                  onChange={(e) => setConnection({ ...connection, name: e.target.value })}
                  placeholder="production-warehouse"
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
            {mode === "edit" && (
              <div className="text-xs text-subtle font-mono">
                id: {connection.id}
              </div>
            )}
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
