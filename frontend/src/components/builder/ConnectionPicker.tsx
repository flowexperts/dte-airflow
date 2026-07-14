"use client";

import useSWR from "swr";
import Link from "next/link";
import { Field } from "@/components/ui";
import type { Connection, ConnectionType } from "@/lib/api";

/**
 * Dropdown of Connection ids filtered by allowed connection_type list.
 * Used by SourceEditor and DestinationForm. No inline creator — users
 * create Connections in `/connections/new` (route it in a new tab).
 */
export function ConnectionPicker({
  value,
  onChange,
  allowedTypes,
  label = "Connection",
}: {
  value: string;
  onChange: (id: string) => void;
  allowedTypes: readonly ConnectionType[];
  label?: string;
}) {
  const { data: all = [], isLoading } = useSWR<Connection[]>("/api/connections");
  const candidates = all.filter((c) => allowedTypes.includes(c.connection_type));

  return (
    <Field
      label={label}
      hint={
        <>
          Credentials come from the linked connection.{" "}
          <Link
            href="/connections/new"
            target="_blank"
            className="text-accent hover:text-accent-h underline"
          >
            create a new one
          </Link>
        </>
      }
    >
      <select
        className="w-full bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="" disabled>
          {isLoading ? "loading…" : "— pick a connection —"}
        </option>
        {candidates.map((c) => (
          <option key={c.id} value={c.id}>
            {c.id} · {c.connection_type}
          </option>
        ))}
        {value && !candidates.find((c) => c.id === value) && (
          <option value={value}>{value} (not found or wrong type)</option>
        )}
      </select>
    </Field>
  );
}
