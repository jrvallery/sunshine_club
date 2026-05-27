import { NextRequest } from "next/server";

const apiBaseUrl = process.env.SUNSHINE_API_URL ?? "http://localhost:8001";

export async function GET(request: NextRequest) {
  const upstream = new URL("/healthz", apiBaseUrl);
  const response = await fetch(upstream, {
    method: request.method,
    cache: "no-store"
  });
  return new Response(response.body, {
    status: response.status,
    headers: response.headers
  });
}
