import { cookies } from "next/headers";
import { COOKIE_NAME, cookieSecure, coreUrl } from "@/lib/server";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "Invalid request" }, { status: 400 });
  }
  let res: Response;
  try {
    res = await fetch(`${coreUrl()}/api/auth/login`, {
      method: "POST",
      // Pass the visitor's address so WAM core rate-limits per visitor, not per admin server.
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": request.headers.get("x-forwarded-for") || request.headers.get("x-real-ip") || "",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "WAM core is not reachable" }, { status: 502 });
  }
  const data = await res.json().catch(() => ({ detail: "Unexpected response from WAM core" }));
  if (!res.ok) return Response.json(data, { status: res.status });
  const store = await cookies();
  store.set(COOKIE_NAME, data.token, {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  return Response.json({ user: data.user });
}
