import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listEvalSets, type EvalSet } from "@/lib/api";
import { EvalSetsTable } from "@/components/evals/evals-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side

export default async function EvalsPage() {
  let sets: EvalSet[] = [];
  let error: HumanError | null = null;
  try {
    sets = await listEvalSets();
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "eval sets" });
  }

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Evals" }]}
        actions={
          <NewResourceButton perm="eval:write" href="/eval-sets/new" label="New eval set" />
        }
      />
      <PageHeader
        title="Evals"
        sub={`${sets.length} total`}
        lede="A labeled corpus turns 'this prompt looks right' into a number you can compare — across configs, and across time."
      />

      <div className="px-14 py-8">
        {error ? (
          <InlineError title={error.title} message={error.message} detail={error.detail} />
        ) : (
          <EvalSetsTable rows={sets} />
        )}
      </div>
    </>
  );
}
