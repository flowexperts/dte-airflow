import { InlineError } from "@/components/ui";

export function MissingParam({ what }: { what: string }) {
  return (
    <div className="px-14 py-8">
      <InlineError title={`No ${what} selected`} message="Open this page from a list so it knows which one." />
    </div>
  );
}
