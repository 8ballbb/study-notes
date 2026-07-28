# Enriching a note with research

You are given one topic's key claims. Use WebSearch/WebFetch to make the note better than the
source — do not pad.

## Do
- Verify the key claims; flag any that are outdated or wrong.
- Add authoritative context or a concrete example the source skipped.
- Surface one or two closely related ideas worth a link.

## Rules
- Every external claim MUST carry a source URL. Return a compact list of additions, each with
  its URL, that the orchestrator can merge. If you find nothing solid, return nothing — the note
  is fine from the source alone.
