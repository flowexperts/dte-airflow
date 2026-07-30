import { NextResponse, type NextRequest } from "next/server";

// Presence check only — the API is the source of truth for signature/expiry.
// If the cookie is stale, apiFetch's 401 handler will clear it and bounce back.
const TOKEN_COOKIE = "dte_token";

const PUBLIC_PATHS = ["/login", "/docs", "/docs-assets", "/marketing"];
const PUBLIC_EXACT = new Set(["/"]);

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC_EXACT.has(pathname)) {
    return NextResponse.next();
  }
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }
  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

// Matcher excludes static assets and Next internals.
export const config = {
  matcher: ["/((?!_next/|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|map|mp4|webm|mov|ogv)$).*)"],
};
