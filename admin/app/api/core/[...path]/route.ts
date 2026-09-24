import { cookies } from "next/headers";
import { COOKIE_NAME, coreUrl } from "@/lib/server";

// Forwards browser calls to WAM core, adding the session token from the httpOnly cookie.
// Only WAM core's /api/* and /health routes are reachable through here.

async function forward(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (!path.length || !["api", "health"].includes(path[0]) || path.some((p) => p === ".." || p === ".")) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  const store = await cookies();
  const token = store.get(COOKIE_NAME)?.value;
  const search = new URL(request.url).search;
  const target = `${coreUrl()}/${path.map(encodeURIComponent).join("/")}${search}`;
  const headers: Record<string, string> = { accept: "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const init: RequestInit = { method: request.method, headers, cache: "no-store" };
  // Binary-safe: file uploads (multipart) must reach WAM core byte for byte.
  if (!["GET", "HEAD"].includes(request.method)) init.body = await request.arrayBuffer();
  let res: Response;
  try {
    res = await fetch(target, init);
  } catch {
    return Response.json({ detail: "WAM core is not reachable" }, { status: 502 });
  }
  if (res.status === 204) return new Response(null, { status: 204 });
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
