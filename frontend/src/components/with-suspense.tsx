import { Suspense, type ComponentType } from "react";

/** `useSearchParams()` needs a Suspense boundary in a static export. */
export function withSuspense<P extends object>(C: ComponentType<P>) {
  return function WithSuspense(props: P) {
    return (
      <Suspense fallback={null}>
        <C {...props} />
      </Suspense>
    );
  };
}
