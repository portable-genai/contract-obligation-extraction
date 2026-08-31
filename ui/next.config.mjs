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
 *
 * The third entry is `agentRules`, and it is a refusal to WRITE rather than a refusal to boot.
 * `next dev` detects an AI coding agent from the environment and, unless this is false,
 * generates `AGENTS.md` and `CLAUDE.md` in this directory: see
 * `node_modules/next/dist/server/lib/generate-agent-files.js`, which is where the behaviour and
 * the flag name can be re-checked after a framework bump. Both files are wrong here, for two
 * separate reasons. The catalog's convention is that `AGENTS.md` is the working agreement and it
 * is the ONLY one, with no tool-specific alias of it anywhere, and this repository already
 * carries its own at the root; a second one under `ui/` is a second working agreement to keep in
 * step, and `CLAUDE.md` is exactly the alias the convention forbids. Separately, the generated
 * prose contains an em-dash, which `make docs-check` fails the build on. Neither appears until
 * somebody starts the dev server, which is the moment a new untracked markdown file is least
 * likely to be noticed, so the generation is turned off at the source rather than deleted by
 * hand in every repo, every time. `tests/unit/test_ui_surface.py` fails the offline gate if this
 * line goes away or if either file turns up on disk anyway.
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
  agentRules: false,
};

export default nextConfig;
