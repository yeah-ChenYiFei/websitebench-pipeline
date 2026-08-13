# Conversation curation brief

Read only the configured archive roots and indexing metadata. Preserve evidence
and extract neutral, reusable lessons; do not implement a clone or alter release
state.

Treat byte-for-byte rollout JSONL as authoritative. Preserve user wording,
timestamp, thread/parent identity, message ordinal, raw locator, archive ID,
and quote SHA-256. Never reconstruct missing text or present a summary as a
user quote. Mark point-in-time snapshots and inherited fork prefixes, and
report hash, count, JSONL, lineage, or readable-derivative drift without
rewriting the original archive.

Minimize private data. Exclude credentials, cookies, tokens, personal data,
and unrelated tool output. Separate exact quotes from generalized observations
and neutral verification questions. Keep site-specific facts in the private
case corpus; only transferable classes, denominators, and probes belong in
shared guidance.

Validate archives with `tools/offline_clone/validate_conversation_archives.py`
and concern provenance with
`tools/offline_clone/validate_conversation_concerns.py`. Return the inventory,
lineage, integrity results, relevant exact messages, structured concerns,
deduplicated probes, uncertainty, and privacy notes.
