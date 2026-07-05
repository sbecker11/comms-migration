"""Phase 5 categorization & action layer.

Reads mail from the mapped Gmail accounts, resolves a category via
``rules/senders.yaml`` + ``rules/actions.yaml`` (falling back to an LLM for
ambiguous senders), and executes the configured action (label, archive,
flag, quarantine, digest).

This package owns *categorization of already-arrived mail*. It does not
decide where a sender should forward to (that's `contacts/` + `rules/senders.yaml`,
Layer 2) and it does not process recruiting mail (that's the sibling
`job-tracker` repo).
"""

from dotenv import load_dotenv

load_dotenv()
