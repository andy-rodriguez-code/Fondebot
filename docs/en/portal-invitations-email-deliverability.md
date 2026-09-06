# Invitation e-mail deliverability (SPF, DKIM, DMARC)

> Leer en español: [portal-invitations-email-deliverability.md](../es/portal-invitations-email-deliverability.md)

When you invite someone to a portal (see [Client portal & domains](client-portal.md)) with `EMAIL_PROVIDER=none` (the default), OpenLivery sends nothing: it still creates the invitation and hands you back the link to relay yourself. This page is for when you turn on `EMAIL_PROVIDER=smtp` and OpenLivery starts sending that mail on its own.

## Why this matters

A receiving mail server does not trust the `From:` header blindly: it asks the sending domain's DNS whether the server that delivered the message was allowed to, and whether the body was tampered with in transit. A sender without those answers in DNS usually is **not bounced** — it is almost always accepted anyway, but dropped into spam, or silently discarded. That is the hardest failure mode to notice: the invitation "sent" (no exception was raised, `delivered_at` is set) and the invited person never sees it.

Three DNS records, on the domain you put in `SMTP_FROM`, fix this:

- **SPF** (Sender Policy Framework) — lists which servers are allowed to send on behalf of your domain.
- **DKIM** (DomainKeys Identified Mail) — the outbound server signs the message with a private key; the receiving side verifies the signature against a public key published in DNS. Proves the body was not altered and that it really came from where it claims to.
- **DMARC** (Domain-based Message Authentication, Reporting and Conformance) — tells the receiver what to do when SPF or DKIM fail (nothing, quarantine it, or reject it), and who to send a report to when that happens.

Without all three, most large providers (Gmail, Outlook, Yahoo) treat the mail as suspicious by default — this is not an optional tuning knob to "improve" delivery, it is the minimum bar for not being dropped outright.

## The short answer: use an authenticated relay

The practical way to solve this for a self-hosted install is **not** to hand-configure SPF/DKIM/DMARC for your own domain: it is to send mail through a transactional e-mail provider (Postmark, SendGrid, Amazon SES, Mailgun, or your hosting provider's own SMTP) whose outbound infrastructure is already correctly authenticated, and simply add your domain as a verified sender there. Most of these providers give you:

1. An SMTP host/username/password to put in `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD`.
2. One or two DNS records (`CNAME` or `TXT`) to verify you own the domain in `SMTP_FROM`, which the provider manages and rotates for you.

With that, DKIM and SPF are handled by the provider; you add DMARC once (see below) because it is a policy about *your* domain, not something a mail provider can declare on your behalf.

## If you'd rather send directly from your own domain

If instead you run your own outbound SMTP server (for example Postfix on the same host, or an internal relay in your organization) and are not going to use a transactional provider, you need all three records on the domain in `SMTP_FROM`.

### SPF

A `TXT` record at the domain root (`example.com`, not a subdomain), authorizing the IPs or host that will send:

```
example.com.  TXT  "v=spf1 ip4:203.0.113.10 include:_spf.your-provider.com -all"
```

- `ip4:` / `ip6:` for your own IPs; `include:` when a third-party provider sends on your behalf (each provider publishes its own).
- `-all` at the end hard-fails anything not on the list. `~all` (softfail) is more permissive while testing, but don't leave it that way in production: it is the difference between "rejected" and "accepted but suspicious".
- Only **one** SPF record is allowed per domain — if you already have one (for another mail service, say), add your source to that same record instead of creating a new one.

### DKIM

Requires your MTA (Postfix + OpenDKIM, or whatever you use) to sign every message with a private key, and for you to publish the matching public key:

```
selector._domainkey.example.com.  TXT  "v=DKIM1; k=rsa; p=<base64-public-key>"
```

`selector` is a name you choose (your MTA names it when generating the key pair); several selectors can be active at once, which is what lets you rotate the key without breaking outbound mail. Configuring DKIM signing in the MTA itself is out of scope here because it depends on the software you picked — OpenDKIM's docs (or your hosting provider's) have the step-by-step.

### DMARC

A `TXT` record at `_dmarc.example.com` declaring the policy and where failure reports go:

```
_dmarc.example.com.  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@example.com"
```

- `p=none` — observe only, no effect on delivery. A reasonable starting point while you confirm SPF/DKIM are correct.
- `p=quarantine` — anything that fails goes to spam. The recommended target for production.
- `p=reject` — anything that fails is rejected outright. Only once you're confident no legitimate mail is failing.
- `rua=mailto:...` is optional but recommended: without reports, there's no way to know SPF/DKIM are failing until someone tells you an invitation never arrived.

## Verifying

Before trusting the setup, send yourself a test invitation to a Gmail or Outlook account and check the received message's headers ("Show original" / "View source" in the mail client): you should see `spf=pass`, `dkim=pass` and `dmarc=pass`. Tools like `dig txt example.com` / `dig txt _dmarc.example.com`, or an online SPF/DKIM/DMARC checker, confirm the DNS records look right before you even send a real message.
