// The same-origin reverse proxy to the service API.
//
// Why a proxy at all, when the browser could call the service directly: because a direct call
// means the browser holds the credential and the service must open CORS to every tenant origin.
// Here the credential stays on the server, the browser only ever talks to its own origin, and the
// tenant allowlist is enforced in one place.
//
// The security-relevant behaviour, in the order it happens:
//
//   1. Every client-asserted identity header is DISCARDED (`stripClientIdentity`). A caller cannot
//      name its own actor, tenant, roles or ACL, however the request was crafted.
//   2. Identity is resolved SERVER-SIDE and the resolved headers are added afterwards, so a
//      stripped header cannot be reintroduced by the same request.
//   3. The service-to-service credential is read from the server environment; it is never sent to
//      the browser and never appears in a client bundle.
//   4. Cross-origin requests are answered only for a REGISTERED tenant origin. An unregistered
//      origin gets no allow-origin header at all, which the browser turns into a denial.

import { NextResponse } from "next/server";

import { corsOriginFor, stripClientIdentity } from "../../../../lib/embed-policy.mjs";
import {
  IdentityError,
  resolveIdentity,
  serviceBaseUrl,
  serviceHeaders,
} from "../../../../lib/server/identity";

// Always dynamic: this route forwards a live request and must never be prerendered or cached.
export const dynamic = "force-dynamic";

const ALLOWED_METHODS = "GET, POST, OPTIONS";

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

function corsHeaders(request: Request): Record<string, string> {
  const origin = corsOriginFor(request.headers.get("origin"), process.env);
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Methods": ALLOWED_METHODS,
    "Access-Control-Allow-Headers": "Content-Type, X-Dev-Persona",
    Vary: "Origin",
  };
}

async function forward(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const target = serviceBaseUrl(process.env) + "/" + path.map(encodeURIComponent).join("/");

  let identity;
  try {
    identity = resolveIdentity(request.headers, process.env);
  } catch (error) {
    const detail = error instanceof IdentityError ? error.message : "identity is not configured";
    return NextResponse.json(
      { detail },
      { status: 401, headers: { ...corsHeaders(request), "Cache-Control": "no-store" } },
    );
  }

  const headers = stripClientIdentity(request.headers);
  for (const [name, value] of Object.entries({
    ...identity.headers,
    ...serviceHeaders(process.env),
  })) {
    headers.set(name, value);
  }

  const body = request.method === "GET" ? undefined : await request.text();
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body,
    redirect: "manual",
    cache: "no-store",
  });

  const out = new Headers(corsHeaders(request));
  out.set("Content-Type", upstream.headers.get("content-type") ?? "application/json");
  out.set("Cache-Control", "no-store");
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: out });
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return forward(request, context);
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  return forward(request, context);
}

export async function OPTIONS(request: Request): Promise<Response> {
  const headers = corsHeaders(request);
  // No allow-origin header means the browser refuses the preflight, which is the intended
  // answer for an origin nobody registered.
  return new NextResponse(null, { status: Object.keys(headers).length ? 204 : 403, headers });
}
