import { redirect } from "next/navigation";

type Params = Promise<{ id: string }>;

/**
 * The detail page edits in place, so a separate edit route would be a second
 * way to do the same thing — and two editors drift. Kept as a redirect rather
 * than deleted so existing links and bookmarks still land somewhere useful.
 */
export default async function PipelineEditRedirect({
  params,
}: {
  params: Params;
}) {
  const { id } = await params;
  redirect(`/pipelines/${encodeURIComponent(id)}`);
}
