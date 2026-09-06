// Thin client wrapper for the public invitation-accept endpoint (Spec:
// Invitation Acceptance). Kept as its own pure, testable function instead of
// an inline fetch inside app/portal/[slug]/invite/page.tsx.
import { api } from "./api";
import type { PortalInvitationAccept, PortalSession } from "@/types";

export function acceptInvitation(slug: string, payload: PortalInvitationAccept): Promise<PortalSession> {
  return api<PortalSession>(`/portal/${slug}/invitations/accept`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
