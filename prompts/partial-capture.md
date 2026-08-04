# PARTIAL CAPTURE (region requested)

The user asked to capture only part of this source, described in their own words (the `only`
directive), not as timestamps. Before you plan any notes:

1. Fetch the full source with timestamps (the transcript's `segments`, and its `chapters` if any).
2. Find the span that matches the user's description. Match on meaning, not exact words — a chapter
   title or a run of segments about the topic they named. If several parts could match, pick the
   best and note the alternatives.
3. Show the user what you found with `ask_user`: the time range (start of the first segment to the
   start of the segment after the last one, or the chapter's end) and a short snippet from each end
   so they can see the boundaries. Ask them to confirm or adjust the range.
4. Once they confirm, treat ONLY that span as the source. Split and write notes from it following
   your normal procedure and the interactive rules above. Ignore the rest of the source.

If you cannot find a plausible match, say so and ask the user to rephrase rather than guessing.
