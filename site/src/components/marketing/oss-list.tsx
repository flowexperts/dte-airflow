import type { Oss } from "@/lib/oss";

export function OssList({ items }: { items: Oss[] }) {
  return (
    <dl className="oss">
      {items.map((o) => (
        <div key={o.name}>
          <dt><a href={o.url} target="_blank" rel="noopener noreferrer">{o.name}</a></dt>
          <dd>{o.role}</dd>
          <dd className="lic">{o.license}</dd>
        </div>
      ))}
    </dl>
  );
}
