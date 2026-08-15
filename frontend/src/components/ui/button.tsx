import Link from "next/link";
import { cn } from "@/lib/cn";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "default" | "primary" | "ghost";
type Size = "sm" | "md";

type AnchorProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  kbd?: string;
  leadingIcon?: ReactNode;
  /**
   * Render as a link styled exactly like a button. For controls that
   * navigate — the styling is about how important the control is, not
   * about which element implements it.
   */
  href?: string;
}

const base =
  "inline-flex items-center gap-1.5 rounded-[var(--radius)] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none";

const variants: Record<Variant, string> = {
  default:
    "bg-surface text-text border border-border-2 hover:bg-hover",
  primary:
    "bg-accent border border-accent text-white hover:bg-accent-h hover:border-accent-h",
  ghost:
    "bg-transparent border border-transparent text-muted hover:text-text hover:bg-hover",
};

const sizes: Record<Size, string> = {
  sm: "px-2 py-1 text-[11.5px]",
  md: "px-3 py-1.5 text-[12.5px]",
};

export function Button({
  variant = "default",
  size = "md",
  kbd,
  leadingIcon,
  className,
  children,
  href,
  ...rest
}: ButtonProps) {
  const classes = cn(base, variants[variant], sizes[size], className);
  const inner = (
    <>
      {leadingIcon}
      {children}
      {kbd ? <Kbd className="ml-1">{kbd}</Kbd> : null}
    </>
  );

  /*
   * A control that navigates is still a control. Rendering it as bare
   * underlined text next to real buttons makes the primary action on a page
   * read as an afterthought and shrinks its click target — the distinction
   * between "action" and "navigation" matters to the code, not to the
   * person looking for the thing to press.
   *
   * An anchor rather than a button with an onClick, so middle-click, ⌘-click
   * and "copy link" all behave, and so it works before hydration.
   */
  if (href !== undefined) {
    // Only `title` is forwarded. Under `exactOptionalPropertyTypes`, Next's
    // LinkProps rejects any optional handler passed as possibly-undefined,
    // so a general spread does not typecheck — and a link-shaped button
    // needs a destination and a tooltip, not an onClick. Matches how
    // `NavItem` and `Topbar` use Link.
    const { title } = rest as AnchorProps;
    return (
      <Link href={href} className={classes} title={title ?? ""}>
        {inner}
      </Link>
    );
  }

  return (
    <button className={classes} {...rest}>
      {inner}
    </button>
  );
}

export function Kbd({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-mono text-[10px] px-1 py-px rounded-sm opacity-70",
        "bg-hover text-current",
        className,
      )}
    >
      {children}
    </span>
  );
}
