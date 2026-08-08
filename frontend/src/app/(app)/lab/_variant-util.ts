/** Variant selection shared by server pages and the client switcher.
 *
 * Kept out of `_variant.tsx` on purpose: that file is "use client", and a
 * server component cannot call a function that lives in a client module — it
 * can only render it as a component or pass it as a prop.
 */

export type Variant = "a" | "b" | "c";

export interface VariantOption {
  value: Variant;
  label: string;
  note: string;
}

/** Narrow an arbitrary `?v=` into a known variant, defaulting to the first. */
export function asVariant(
  v: string | undefined,
  allowed: [Variant, ...Variant[]],
): Variant {
  return allowed.includes(v as Variant) ? (v as Variant) : allowed[0];
}
