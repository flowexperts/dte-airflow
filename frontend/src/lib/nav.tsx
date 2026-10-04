/**
 * Next-shaped navigation over Airflow's own react-router (plan 066).
 *
 * DTE renders inside Airflow's route `plugin/:page/*`, so every DTE path
 * (`/pipelines/detail?id=x`) lives under `/plugin/<page>`. These wrappers add
 * and strip that base, which is why page code still writes app-absolute
 * paths as it did under Next.
 */
import { useMemo, type AnchorHTMLAttributes } from "react";
import { useSWRConfig } from "swr";
import {
  Link as RouterLink,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams as useRouterSearchParams,
} from "react-router-dom";

export function useBase() {
  return `/plugin/${useParams().page ?? "dte"}`;
}

// Each section belongs to one Airflow nav entry (plugin.py). An absolute
// href is mounted under its owner, not the current page, so a pipeline →
// source link lands under Admin ▸ DTE Sources and the rail highlights it.
const OWNED = ["/sources", "/destinations", "/lookup-tables"];
export const ownerOf = (href: string) => {
  const s = OWNED.find((p) => href === p || href.startsWith(p + "/") || href.startsWith(p + "?"));
  return `/plugin/${s ? "dte-" + s.slice(1) : "dte"}`;
};
const join = (_base: string, href: string) => (href.startsWith("/") ? ownerOf(href) + href : href);

export function Link({
  href,
  ...rest
}: { href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <RouterLink to={join(useBase(), href)} {...rest} />;
}

export function useRouter() {
  const navigate = useNavigate();
  const base = useBase();
  const { mutate } = useSWRConfig();
  return useMemo(
    () => ({
      push: (href: string) => void navigate(join(base, href)),
      replace: (href: string) => void navigate(join(base, href), { replace: true }),
      back: () => void navigate(-1),
      // All data is SWR-fetched, so "refresh" means revalidate every key.
      refresh: () => void mutate(() => true),
    }),
    [navigate, base, mutate],
  );
}

export function usePathname() {
  const base = useBase();
  const { pathname } = useLocation();
  return pathname.startsWith(base) ? pathname.slice(base.length) || "/" : pathname;
}

export function useSearchParams() {
  return useRouterSearchParams()[0];
}
