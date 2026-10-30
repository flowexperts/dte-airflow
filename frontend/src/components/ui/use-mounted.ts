import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** False during SSR/hydration, true on the client after — gates portals. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
