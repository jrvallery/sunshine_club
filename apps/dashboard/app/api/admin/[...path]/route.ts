import { NextRequest } from "next/server";

const apiBaseUrl = process.env.SUNSHINE_API_URL ?? "http://localhost:8001";

export async function proxyAdmin(request: NextRequest, pathParts: string[]) {
  const url = new URL(request.url);
  const upstream = new URL(`/admin/${pathParts.join("/")}${url.search}`, apiBaseUrl);
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(upstream, {
    method: request.method,
    headers: {
      "content-type": request.headers.get("content-type") ?? "application/json"
    },
    body,
    cache: "no-store"
  });
  return new Response(response.body, {
    status: response.status,
    headers: response.headers
  });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyAdmin(request, params.path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyAdmin(request, params.path);
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyAdmin(request, params.path);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyAdmin(request, params.path);
}
