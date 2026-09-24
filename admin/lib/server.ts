export const COOKIE_NAME = "wam_token";

export function coreUrl(): string {
  return (process.env.CORE_URL || "http://localhost:8000").replace(/\/$/, "");
}

export function cookieSecure(): boolean {
  if (process.env.COOKIE_SECURE) return process.env.COOKIE_SECURE === "true";
  return process.env.NODE_ENV === "production";
}
