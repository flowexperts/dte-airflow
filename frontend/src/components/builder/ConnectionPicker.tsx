"use client";

import useSWR from "swr";
import Link from "next/link";
import { Dropdown, Field, type DropdownOption } from "@/components/ui";
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
      <Dropdown<string>
        value={value}
        onChange={onChange}
        placeholder={isLoading ? "loading…" : "— pick a connection —"}
        options={[
          ...candidates.map<DropdownOption<string>>((c) => ({
            value: c.id,
            label: c.id,
            meta: c.connection_type,
          })),
          ...(value && !candidates.find((c) => c.id === value)
            ? ([{ value, label: `${value} (not found or wrong type)`, disabled: true }] as DropdownOption<string>[])
            : []),
        ]}
      />
    </Field>
  );
}
