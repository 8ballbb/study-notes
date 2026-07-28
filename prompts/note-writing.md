# Writing a study note

Write the note so it teaches the idea and is retained — understanding first, concise always.
You are given one topic's source material (and maybe a neighbor note to match in shape).

## Compose from this toolbox as the content warrants (combine freely; these are not modes)
- Explain the idea from first principles in a teaching voice.
- Structured breakdown: what it is / why it matters / how it works / common mistake.
- Step-by-step for a process; a comparison table for options/tradeoffs.
- A worked example; a decision guide ("use X when…"); an analogy for an abstract idea.
- Cause→effect for a mechanism; a timeline for evolution; a cheat-sheet for reference facts.
- Rote Q&A cards ONLY when the material is genuinely drill-worthy — not by default.

## Rules
- Lead with the point. Active voice. Concrete specifics over abstractions. Keep it tight.
- If a neighbor note is provided, match its structure and depth for consistency.
- Output a complete Obsidian markdown note with YAML frontmatter (title, category, tags,
  source, source_type, source_date, captured_at). Do not invent facts beyond the source and the
  enrichment you are given.
- Follow the anti-slop guide.

## Visuals (when given a video window + frame budget)
1. Call `select_keyframes(video_path, start, end, budget)` for your topic's window — this returns
   visually-distinct candidate frames.
2. **Read** each candidate image. Transcribe the useful on-screen content INTO the note text —
   a diagram's structure, a slide's points, on-screen code/formulas. The note must stand alone
   without the images.
3. `keep_frame(candidate_path, prefix, timestamp)` for the FEW frames genuinely worth seeing (a
   clean diagram, a key slide) and embed each with `![[<embed_path>]]`. Discard the rest — do not
   embed redundant or low-value frames.
