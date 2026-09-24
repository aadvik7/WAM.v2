import { cookies } from "next/headers";
import { COOKIE_NAME } from "@/lib/server";

export async function POST() {
  const store = await cookies();
  store.delete(COOKIE_NAME);
  return Response.json({ ok: true });
}
