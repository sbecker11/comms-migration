# comms-migration

**Routing** — where mail goes (hubs, contacts, sender rules, Gmail classify/label).

Processing after mail arrives is **not** owned here → sibling
[`job-tracker`](../job-tracker/). Scheduling →
[`recruiting-automation`](../recruiting-automation/).

Umbrella install / ops: [`../README.md`](../README.md) (or [`docs/WORKSPACE.md`](docs/WORKSPACE.md))  
Secrets / git-crypt: [`../SECRETS.md`](../SECRETS.md) (or [`docs/SECRETS.md`](docs/SECRETS.md))  
Full historical detail: [`docs/REFERENCE.md`](docs/REFERENCE.md)  
Runbook: [`comms-migration-runbook.md`](comms-migration-runbook.md) ·  
Routing record: [`routing-inventory.md`](routing-inventory.md)

## What this repo owns

| Owns | Does not own |
|------|----------------|
| Two-hub model (Professional / Personal) | JD scoring, résumé packages |
| `contacts/Contacts.yaml` + `rules/senders.yaml` (local data) | Hourly launchd schedule |
| `rules/rules.yaml` + `rules/actions.yaml` (committed policy) | Recruiting CRM / leads DB |
| Gmail classifier (label / archive / spam sweep) | |

**Handoff:** mail labeled for the recruiting funnel → `job-tracker` processes it.

## Real data never gets committed

| Real file (gitignored) | Committed stub |
|------------------------|----------------|
| `contacts/Contacts.yaml` | `contacts/Contacts.yaml.example` |
| `rules/senders.yaml` | `rules/senders.yaml.example` |

Never `git add -f` either real file. Commit **policy**; ignore **who**.

## Quick start

```bash
cp pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

# Unlock .env (see ../SECRETS.md), then:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp contacts/Contacts.yaml.example contacts/Contacts.yaml   # then populate
python scripts/export_senders_cli.py

# Dry-run classifier (needs OAuth under ~/.config/comms-classifier/ — see below)
python scripts/run_classifier.py --account personal_hub --dry-run --limit 10
```

## Common commands

| Goal | Command |
|------|---------|
| Regenerate routing table | `python scripts/export_senders_cli.py` |
| Default unassigned → Personal | `python scripts/default_contacts_personal.py` |
| Contacts UI | `python contacts_app/main.py` |
| Classify (dry-run) | `python scripts/run_classifier.py --account personal_hub --dry-run --limit 25` |
| Validate rules | `python scripts/validate_rules.py` |
| Dead-rule telemetry | `python scripts/check_dead_rules.py` |
| Tests / coverage | `./scripts/coverage.sh` |
| Workspace coverage | `../report-coverage.sh` |

## Layers (commit policy, ignore data)

1. **Data** — `contacts/Contacts.yaml` (gitignored)  
2. **Routing** — `rules/senders.yaml` (generated, gitignored)  
3. **Actions** — `rules/actions.yaml` + `rules/rules.yaml` (committed)

Match order: exact email → phone → domain → overrides → default.

Classifier resolution: `rules.yaml` → `senders.yaml` → LLM fallback → `spam_unknown`.

## Gmail OAuth (one-time)

Needs `gmail.modify` (separate tokens from job-tracker even for the same account):

```bash
mkdir -p ~/.config/comms-classifier/{personal_hub,recruiting_funnel}
cp ~/Downloads/client_secret_*.json ~/.config/comms-classifier/personal_hub/credentials.json
cp ~/.config/comms-classifier/personal_hub/credentials.json \
   ~/.config/comms-classifier/recruiting_funnel/credentials.json

python scripts/run_classifier.py --account personal_hub --dry-run --limit 10
python scripts/run_classifier.py --account recruiting_funnel --dry-run --limit 10
```

Prefer shared `ANTHROPIC_API_KEY` in `../.env` (see umbrella README).  
Deep OAuth / spam-sweep / Z3 notes: [`docs/REFERENCE.md`](docs/REFERENCE.md).

## `.env` / git-crypt

Tracked + encrypted. Unlock steps: [`../SECRETS.md`](../SECRETS.md)  
(key file: `~/.git-crypt-keys/comms-migration.key`).
