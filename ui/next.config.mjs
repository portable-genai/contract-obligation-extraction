/**
 * Next configuration for the embeddable console.
 *
 * `output: "standalone"` so the production image copies only what the server needs (the same
 * minimal-runtime rule the Python image follows). Security headers are NOT set here: they come
 * from `proxy.ts`, which shares one policy module with the API route, because a header set in two
 * places is a header that disagrees with itself.
 *
 * What IS here is the refusal. `next build` and `next start` both evaluate this file at module
 * scope, so resolving the embedding policy here makes a policy nobody chose a BUILD or BOOT
 * failure rather than a surprise on some later request. `UI_FRAME_ANCESTORS=` and
 * `UI_TENANT_ORIGINS=` (a Terraform variable that rendered to nothing, a `.env` line left blank)
 * must not be byte-identical to never having set them: a deployment that lost its allowlist
 * would look exactly like one that locked itself down. It does not come up at all.
 *
 * The second refusal is the hydration one. `proxy.ts` mints a per-request nonce, and Next can
 * only stamp that nonce onto the scripts of a DYNAMICALLY rendered route. If `app/layout.tsx`
 * ever loses `export const dynamic = "force-dynamic"`, the page goes back to being prerendered at
 * build time, nothing carries the nonce, and `'strict-dynamic'` blocks every script including the
 * ones plain `'self'` would allow. The page still renders, the headers still look right and the
 * module tests still pass; only a browser notices that React never attached. So it is refused
 * here, where a build can fail, rather than left to be discovered in a console.
 */
import { readFileSync } from "node:fs";

import { assertEmbedPolicyConfigured, assertHydratableCsp } from "./lib/embed-policy.mjs";

assertEmbedPolicyConfigured(process.env);
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
