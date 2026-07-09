import type { DltSource } from "@/lib/api";

export type SourceKind = "filesystem" | "sql_database" | "mongodb";

export const SOURCE_KINDS: { value: SourceKind; label: string }[] = [
  { value: "filesystem",   label: "Filesystem / S3" },
  { value: "sql_database", label: "SQL" },
  { value: "mongodb",      label: "MongoDB" },
];

export function emptySource(id = ""): DltSource {
  return {
    id,
    source_type: "filesystem",
    config: { bucket_url: "", file_glob: "*.json" },
    table: id || "table",
  };
}
