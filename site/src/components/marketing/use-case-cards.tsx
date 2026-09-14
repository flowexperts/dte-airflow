import Link from "next/link";
import { USE_CASES } from "@/lib/use-cases";

/** The five use cases, as cards. Landing page and the cross-links at the
 *  bottom of each use-case page both render this. */
export function UseCaseCards({ exclude }: { exclude?: string }) {
  const shown = exclude ? USE_CASES.filter((u) => u.slug !== exclude) : USE_CASES;

  return (
    <div className="steps-grid">
      {shown.map((u) => (
        <Link key={u.slug} className="steps-card uc-card" href={`/use-cases/${u.slug}/`}>
          <span className="uc-card-dept">{u.dept}</span>
          <span className="steps-card-label">{u.pick}</span>
          <span className="steps-card-hint">{u.headline}</span>
        </Link>
      ))}
    </div>
  );
}
