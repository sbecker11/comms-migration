# comms-migration — Cursor project instructions

**Humans:** [`README.md`](README.md) · umbrella [`docs/WORKSPACE.md`](docs/WORKSPACE.md) · secrets [`docs/SECRETS.md`](docs/SECRETS.md).

Single source of truth for **routing**: which hub/inbox a sender lands in, and
the four-into-one forward into `shawnbecker.recruiting@gmail.com`.

Processing after mail arrives (classify → score → packages) is **not** owned
here — that lives in sibling `job-tracker/`. Scheduling lives in
`recruiting-automation/`.

## Real data never gets committed

| Real file (gitignored) | Committed stub |
|---|---|
| `contacts/Contacts.yaml` | `contacts/Contacts.yaml.example` |
| `rules/senders.yaml` | `rules/senders.yaml.example` |

- **Never** `git add -f` either real file.
- Any new file **derived from** contacts inherits the same rule — gitignore it
  and add an `.example` stub.
- Commit **policy** (how routing works); ignore **who** (real names/emails/phones).

## Layers (commit policy, ignore data)

1. **Data** — `contacts/Contacts.yaml` (gitignored)
2. **Routing** — `rules/senders.yaml` (generated, gitignored)
3. **Actions** — `rules/actions.yaml` + `rules/rules.yaml` (committed; no personal data)

## Candidate profile

This repo does **not** generate résumés or cover letters. Do not invent
candidate experience here.

If a change touches JD evaluation, package content, or dealbreakers, hand off
to `../job-tracker/` and load `~/CLAUDE.md` there — do not fork profile rules
into this repo.
