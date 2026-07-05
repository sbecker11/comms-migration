# Routing Inventory

**Part of:** comms-migration
**Owner:** Shawn Becker · Spexture
**Purpose:** Single source of truth for where every category of incoming mail
routes. If a forward or filter exists anywhere, it is recorded here — nothing
invisible.

---

## Model

Two hubs, plus one special-purpose funnel:

- **Professional chain** — `shawn.becker@spexture.com` + Nextiva number.
  Categorized/processed business communications.
- **Personal hub** — consolidated personal inbox, walled off from business.
- **Recruiting funnel** — `shawnbecker.recruiting@gmail.com`. A dedicated
  account because it feeds the job-search automation pipeline, which needs a
  clean inbox to read. (See cross-reference below.)

Rule of thumb: a category gets its **own account** only if it feeds automation.
Everything else lands in the correct hub and is organized by **label/filter** —
not by spinning up another account.

---

## 1. Forwards (true redirects)

### Recruiting funnel — three-into-one

**Corrected 2026-07-04:** this table previously listed `scbboston@gmail.com`
as a fourth leg forwarding into the recruiting funnel. Verified directly
against the live Gmail API (`scripts/check_forwarding.py --account
personal_hub`) that this is **not the case** — `scbboston@gmail.com` has no
auto-forwarding, no registered forwarding addresses, and no filter that
forwards mail. It is a dead-end hub; recruiter/job mail that lands there
does not reach the recruiting funnel on its own (see
`comms-migration-runbook.md` Phase 5 / `classifier/` and job-tracker's
`personal_hub` polling, which exist specifically to bridge that gap).

Three source addresses forward into `shawnbecker.recruiting@gmail.com`:

| Source address                                          | Mechanism                                        | Notes                                              |
| ------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------- |
| `shawn.becker@spexture.com`                             | Hostinger (hPanel) forwarder, **keep-a-copy ON** | Passive backup only as of 2026-07-04 — see note below. **Canary-verified 2026-07-04**: arrived in ~4 min. |
| `scb_boston@yahoo.com` (alias `shawn.becker@yahoo.com`) | Yahoo Mail Plus auto-forward                     | Near-real-time push; Plus is a paid feature. **Canary-verified 2026-07-04**: arrived in ~6 min. |
| `sbecker@alum.mit.edu`                                  | **Fixed and confirmed working as of 2026-07-04 ~1:40 PM MT** | **Full timeline:** (1) Canary `CANARY-MIT-20260704-001331` (~12:13 AM MT) exposed MIT had no active forwarding address — mail was accepted by MIT but never forwarded. (2) Forwarding address list updated ~12:31 PM MT via MIT Infinite Connection, confirmed by automated email from `help@alum.mit.edu`; Delivery Options confirmed set to "Deliver and forward." (3) Retest canary `CANARY-MIT-RETEST-20260704-124103` sent 12:41 PM MT — only 10 minutes after the address update — never forwarded either; landed only in the MIT-hosted alumni Outlook mailbox. Given MIT's own "up to 1 hour" propagation guidance, this message is presumed to have been received by MIT's mail system before forwarding fully activated on their backend, and (like the original canary) simply won't be retroactively forwarded — treat both as expected casualties of the transition window, not evidence of an unresolved problem. (4) A further manual test (`PEACOCK`, sent ~1:39-1:40 PM, well into/past the propagation window) **was confirmed forwarded correctly** to `shawnbecker.recruiting@gmail.com`. **Conclusion: forwarding is fixed and working.** Recruiting funnel account itself was confirmed healthy throughout (other real mail, e.g. LinkedIn/Ladders job digests, flowing and labeling normally). Historical backlog risk remains: unknown how long forwarding was inactive before today — still worth a one-time check of the alumni Outlook mailbox for any real mail (not just test canaries) that arrived during that window and was never forwarded. |

**Decision (2026-07-04): dropped Mac Mail as the daily client, kept
`keep-a-copy` ON.** Gmail (the recruiting funnel) is now the sole place
mail is read/triaged day to day — Mail.app and manually checking the
Hostinger mailbox are no longer part of the routine. `keep-a-copy` stays
enabled on the Hostinger forwarder as a passive backup: it costs nothing
(no client required to benefit from it, mail just accumulates server-side
on Hostinger), and it's the only fallback if the forward to Gmail ever
silently fails. It was deliberately *not* disabled — that would remove the
last line of defense against mail loss with no way to detect a failure
after the fact. Revisit disabling it only after a real validation period
(check the Hostinger mailbox for evidence of any forwarding gaps, confirm
a fresh end-to-end test lands correctly) — that's a separate, deliberate
decision from "stop using Mail.app."

Separately, per Phase 2, `sbecker@alum.mit.edu` and `shawn.becker@yahoo.com`
are *also* meant to forward into `scbboston@gmail.com` (personal hub) — that
part is unverified here and worth spot-checking the same way if it matters
(a single source address can have multiple forwarding destinations
configured independently).

**Outbound:** "Send mail as" configured via Hostinger SMTP
(`smtp.hostinger.com`, port 465/SSL, full address as username) so replies go
out as `shawn.becker@spexture.com` with clean SPF/DKIM. "Always reply from
default address" is set so no source leg leaks on a reply.

**Filters in the recruiting account:** `Job-Digests` label (amber) applied to
LinkedIn job-alert digests via a `jobalerts-noreply@linkedin.com` filter.

> **Cross-reference:** This funnel exists to feed the job-search / recruiting
> automation pipeline (email classifier → JD evaluation framework → ATS JD
> resolver → job tracker). The _forward_ is routing truth and lives here; the
> _processing_ logic lives in the job-search repo, not in comms-migration.

---

## 2. Categorization routes (label within a hub)

These are not separate accounts. They land in the correct hub and are
organized by label/filter.

| Category  | Destination  | Label / handling                                                                                 | Sensitivity                     |
| --------- | ------------ | ------------------------------------------------------------------------------------------------ | ------------------------------- |
| Politics  | Personal hub | Newsletters/advocacy; good archive-on-arrival candidate                                          | Low                             |
| Church    | Personal hub | Ward/stake communications                                                                        | Low                             |
| Investing | Personal hub | Brokerage/statements                                                                             | **High** — financial + identity |
| Insurance | **Split**    | Health/auto/home → personal; Spexture liability → professional                                   | Med–High                        |
| Billing   | **Split**    | Spexture tools/subscriptions → professional (expense triage); utilities/personal subs → personal | **High** — payment methods      |

---

## 3. Split categories

`Insurance` and `Billing` route to **both** hubs, sorted per-sender by purpose.
This is not a new rule — it's the existing destination rule applied
consistently: **business tools and expenses → professional chain; personal →
personal.** Recorded as split so the inventory doesn't imply a single clean
forward.

---

## 4. Sensitive categories — final-phase migration

`Investing`, `Insurance`, and `Billing` carry financial / identity data and are
typically recovery- and 2FA-bound. Handle these **last** and deliberately:

1. Update the new address first.
2. Confirm it receives.
3. Verify account recovery still works.
4. Only then remove the old address.

**VoIP caveat:** Do **not** route these to the Nextiva number for SMS one-time
codes — banks and brokerages frequently reject VoIP for 2FA. Keep a standard
mobile line for their verification.

---

## Maintenance

When a new forward or filter is created anywhere, add a row here in the same
session. The hub inboxes double as a self-maintaining worklist: anything still
arriving at an old surface is a sender not yet migrated.
