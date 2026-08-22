// The document-layer security header baseline (Next 16 names this file `proxy.ts`).
//
// It applies the SAME policy module the API route uses, so the framing rule the page is served
// with and the CORS rule the data path enforces cannot disagree. Nothing here authenticates:
// authentication belongs to the platform in front of this UI and to the service behind it. What
// this does is make sure every response leaves with the headers, including the error ones.

import { type NextRequest, NextResponse } from "next/server";

import { generateNonce, securityHeaders } from "./lib/embed-policy.mjs";

export function proxy(request: NextRequest) {
  // One nonce per request, and it has to reach BOTH sides or hydration fails in one of two ways.
  // On the REQUEST headers, under the `Content-Security-Policy` name, is where Next looks for the
  // nonce it stamps onto every script tag it emits; a custom header name is silently ignored. On
  // the RESPONSE is what the browser enforces. A nonce on only the response blocks the very
  // scripts it was added to allow; a nonce on only the request proves nothing.
  const nonce = generateNonce();
  const headers = securityHeaders(process.env, nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", headers["Content-Security-Policy"]);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  for (const [name, value] of Object.entries(headers)) {
    response.headers.set(name, value);
  }
  return response;
}

export const config = {
  matcher: "/:path*",
};
