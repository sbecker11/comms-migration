# Coverage policy (comms-migration)

Target: **≥90% line coverage per file** under `classifier/`, plus overall package ≥90% when feasible. Branch coverage is tracked but not gated yet.

## CI gate (2026-08-19)

`.coveragerc`'s `[report] fail_under = 80` is a **hard gate**, enforced
automatically by `pytest-cov` whenever `--cov` runs (no extra CLI flag
needed — see `.github/workflows/tests.yml`, which fails the build if
`classifier/`'s combined coverage drops below 80%). Actual combined
coverage is ~96% as of this writing, so this floor has real headroom; it's
set at 80 rather than the aspirational 90% per-file target below so a
single weak file doesn't need to block CI while the per-file cleanup is
still in progress.

## How to run

```bash
./scripts/coverage.sh          # pytest + term/JSON report + soft per-file check
./scripts/check_per_file_coverage.py   # report-only against coverage.json
./scripts/check_per_file_coverage.py --fail-under 70   # interim soft per-file gate (independent of the hard 80% overall CI gate above)
```

Hard per-file `fail_under=90` is **not** enabled until most files clear 90%. Contacts apps and top-level scripts are out of scope for this measurement.

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
