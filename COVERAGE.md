# Coverage policy (comms-migration)

Target: **≥90% line coverage per file** under `classifier/`, plus overall package ≥90% when feasible. Branch coverage is tracked but not gated yet.

## How to run

```bash
./scripts/coverage.sh          # pytest + term/JSON report + soft per-file check
./scripts/check_per_file_coverage.py   # report-only against coverage.json
./scripts/check_per_file_coverage.py --fail-under 70   # interim soft gate
```

Hard `fail_under=90` is **not** enabled until most files clear 90%. Contacts apps and top-level scripts are out of scope for this measurement.

## Measured source

- Package: `classifier/`
- Config: `.coveragerc` (and optional `[tool.coverage.*]` if a `pyproject.toml` is added later)

## Omit allowlist

| Pattern | Why |
|---|---|
| `*/__main__.py` | Entry wrappers |
| `if __name__ == "__main__":` blocks | Pragma where present |
| Optional-import failure paths already marked `# pragma: no cover` | Defensive ImportError for Google libs |

Do **not** mass-omit `gmail_client.py`, `run.py`, or `models.py` — cover with fakes/unit tests.

## Color thresholds

- Green ≥90%
- Yellow ≥70%
- Red &lt;70%
