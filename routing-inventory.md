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

### Recruiting funnel — four-into-one

Four source addresses forward into `shawnbecker.recruiting@gmail.com`:

| Source address                                          | Mechanism                                        | Notes                                              |
| ------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------- |
| `shawn.becker@spexture.com`                             | Hostinger (hPanel) forwarder, **keep-a-copy ON** | Apple Mail still sees a backup copy                |
| `scb_boston@yahoo.com` (alias `shawn.becker@yahoo.com`) | Yahoo Mail Plus auto-forward                     | Near-real-time push; Plus is a paid feature        |
| `sbecker@alum.mit.edu`                                  | MIT deliver-and-forward                          | Highest spam-risk leg on the forward hop — monitor |
| `scbboston@gmail.com`                                   | Gmail                                            | Working Gmail; forwarded in                        |

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
