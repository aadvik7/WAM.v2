import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Send signed-out visitors to /login. The session cookie is httpOnly and verified by WAM core on
// every API call; this check only avoids rendering app pages for visitors without one.
export function proxy(request: NextRequest) {
  const token = request.cookies.get("wam_token")?.value;
  if (!token) {
    const url = new URL("/login", request.url);
    const next = request.nextUrl.pathname + request.nextUrl.search;
    if (next !== "/") url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
