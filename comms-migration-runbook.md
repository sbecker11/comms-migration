# Communications Consolidation & Migration Runbook

**Owner:** Shawn Becker · Spexture
**Goal:** Route business communications into one categorized/processed chain, keep personal communications in a separate walled-off hub, and migrate senders from old surfaces to their correct permanent home incrementally — with zero lost messages in the meantime.

---

## End-state architecture

Two destinations. Every sender routes to exactly one.

**Professional chain (categorized / processed)**
- Email: `shawn.becker@spexture.com`
- Phone & text: `(385) 403-3248` (hosted in Nextiva)
- Nextiva handles transcription, classification, routing, summaries for these channels.

**Personal hub (walled off — never touches Nextiva)**
- One consolidated inbox fed by the old personal addresses:
  - `sbecker@alum.mit.edu`
  - `shawn.becker@yahoo.com`
  - `scbboston@gmail.com`
- Friends and family keep using whatever old address they know — they change nothing.

---

## Phase 0 — Lock the two open decisions

- [ ] **Old phone number:** port it into Nextiva (preserves continuity, no lost texts) **or** clean cutover (rely on the announcement). *Decision: __________*
- [ ] **Personal hub address:** which inbox is canonical? Gmail recommended for its fetch + send-as + filter capabilities. *Decision: __________*
- [ ] **Destination rule defined:** business-relevant senders → professional; personal senders → personal hub. Sort up front so you're not deciding ad hoc per vendor.

---

## Phase 1 — Stand up the professional telephony chain (Nextiva)

- [ ] Port `(385) 403-3248` into Nextiva so it *hosts* the number (required for texts — SMS cannot be forwarded).
- [ ] Start **10DLC / A2P texting registration immediately** — it has lead time and SMS won't work until it clears.
- [ ] Enable **voicemail-to-email + transcription** (transcription requires voicemail stored on Nextiva's system).
- [ ] Connect `shawn.becker@spexture.com` as an email channel in Nextiva — *or* plan the custom aggregator (Gmail/Workspace API) if you want full control.
- [ ] Verify: test call, test text, and a voicemail all land and process correctly.

---

## Phase 2 — Stand up the personal hub

- [ ] Confirm the hub inbox (Phase 0 decision).
- [ ] **MIT alum** (`sbecker@alum.mit.edu`): it's a forwarding alias — point its destination at the hub.
- [ ] **Yahoo** (`shawn.becker@yahoo.com`): already on **Yahoo Mail+** (paid) — auto-forwarding is available. Point Yahoo's forward destination at the hub. *(POP-fetch via Gmail's "Check mail from other accounts" is only needed if you drop Mail+.)*
- [ ] **Old Gmail** (`scbboston@gmail.com`): forward/fetch into the hub, or make it the hub itself.
- [ ] Configure **"Send mail as"** for each alias so replies go out from the address the sender used.
- [ ] Configure **labels by to-address** (provenance + doubles as migration tracking).
- [ ] **Secure the hub:** strong unique password + 2FA — it now aggregates three identities, so it's a single point of compromise.
- [ ] Verify: send a test to each old address and confirm it lands in the hub and you can reply *as* that address.

---

## Phase 3 — Announce (only after Phase 1 is verified working)

> Sequencing matters: announce **after** the port + 10DLC registration complete, or early texters hit a dead number.

- [ ] Email blast to contacts (professional variant — see Appendix A).
- [ ] One-time text from the new number so it lands in people's threads with caller ID.
- [ ] LinkedIn note for professional contacts without your email.

Three drafted variants (professional / casual / short text) are available in the chat thread.

---

## Phase 4 — Incremental sender migration (the ongoing work)

**The hub is your safety net and your worklist.** Every message still arriving at an old address = a sender not yet migrated. When a sender goes quiet on the old address, it's done. Use `pending` / `migrated` labels to track.

**Safe-swap procedure per account:**
1. Add and verify the new contact info (email and/or phone).
2. Confirm receipt at the new destination.
3. Confirm 2FA / recovery still works.
4. Only then remove the old info.

**Sequencing:** low-stakes marketing & e-commerce first (build the routine) → financial, identity, and 2FA-bound accounts last (move deliberately).

**Cautions:**
- **VoIP 2FA rejection:** the Nextiva number is VoIP; many banks and security-sensitive services reject VoIP numbers for SMS OTP. Keep a real mobile line for those. Test on a low-stakes account first.
- **Never orphan a recovery path** mid-switch.
- **Some senders never honor changes** (marketing lists). That's fine — the hub keeps catching them; filter or ignore.

**Destination reminder:** business purchases / tools / subscriptions → professional chain; personal shopping → personal hub. Don't pollute the business chain with personal receipts.

---

## Phase 5 — Categorization & action layer (optional, later)

**Native Nextiva** gives you sentiment, classification, routing, and post-interaction summaries for its channels out of the box.

**Custom classifier** (your build) for full control and a single pane:
- Normalize every channel to one schema (Appendix B).
- Categorize by **source + subject + content**.
- Action tiers: **Notify now** → **Digest** → **Draft for approval** → **Auto-handle**.
- Keep **human-in-the-loop** on client/recruiter-facing actions; promote categories to full automation only after watching them behave.
- The same classifier can point at the personal hub if you ever want uniform processing under *your* control rather than the vendor's.

---

## Appendix A — Professional announcement (email)

**Subject:** Updated contact info — new phone number

> Hi all,
>
> A quick housekeeping note. My email is unchanged and remains the best way to reach me: shawn.becker@spexture.com.
>
> My phone and text number, however, has changed. Please update your records:
>
> **New number: (385) 403-3248**
>
> Going forward, please use this number for any calls or texts. Email stays the same for anything detailed.
>
> Thanks,
> Shawn Becker
> Spexture

---

## Appendix B — Normalized message schema

```
{
  message_id,
  channel:        voice_vm | sms | email,
  received_at,
  sender: { display_name, address_or_number, known_contact: bool,
            relationship: client | recruiter | vendor | personal | unknown },
  subject,        // email subject; derived or empty for voice/sms
  body,           // voicemail transcript for voice_vm
  thread_id,
  category,       // assigned by classifier
  urgency,        // low | normal | high
  suggested_action
}
```

## Appendix C — Category → signal → action

| Category | Trigger signals | Default action |
|---|---|---|
| Active client | Known client domain/number | Notify now; draft reply (hold for approval) |
| Recruiter / job | Recruiter language, JD content, scheduling | Tag → match-triage; draft acknowledgment for review |
| Personal | Known personal contact | Route to personal hub |
| Financial / admin | Banks, invoices, account notices | Flag; no auto-action |
| Vendor / transactional | Receipts, confirmations, newsletters | Daily digest |
| Spam / unknown | Unrecognized sender | Quarantine |
