import type { ReactNode } from "react";

import { ProvenanceBanner } from "./ProvenanceBanner";
import "./globals.css";

// The title is intentionally generic. The service's own identity comes from its agent card at
// runtime, so this file does not have to be edited when the repo is renamed or reused.
export const metadata = {
  title: "Agent console",
  description: "Embeddable micro-frontend for a catalog agent service.",
};

// Required by the nonce-based CSP in `lib/embed-policy.mjs`, not a performance preference.
// Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route;
// a statically prerendered page was built before the nonce existed, so the browser blocks every
// script and the console renders as dead HTML. `assertHydratableCsp` fails the build if this
// line is removed. An embeddable console resolves identity per request anyway, so there is
// nothing here that a static render could have safely cached across tenants.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ProvenanceBanner />
        {children}
      </body>
    </html>
  );
}
