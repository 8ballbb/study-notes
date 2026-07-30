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
- Start the note with a `# ` H1 title, then the body. The YAML frontmatter is assembled for you
  (OKF-aligned: `type`, `resource`, `timestamp`, `category`, `source_type`) — you may optionally
  lead with a small frontmatter block carrying just `description:` (one line) and `tags: [..]` and
  they will be kept; anything else there is ignored. Do not invent facts beyond the source and the
  enrichment you are given.
- Put external, enrichment-derived sources under a final `## Citations` section, each a bullet with
  its URL (the OKF citations convention). Leave in-source facts un-cited.
- Follow the anti-slop guide.

## Visuals (when given a `video_path` + window + frame budget)
Work text-first, then target frames only where they add. Do NOT scan the whole window.

1. **Draft from the transcript first.** Write the teaching note from the text alone before
   touching any video.
2. **Find the visual-cue moments.** Re-scan your timestamped transcript for the specific points
   where a visual would genuinely add — an on-screen diagram/graph/slide/formula/code/animation,
   or deixis ("as you see here", "this graph", "on the left", "notice that"). Collect each cue's
   timestamp. If there are none, usually extract nothing (but see the backstop).
3. **Extract only around each cue (narrow windows).** For each cue, call
   `select_keyframes(video_path, start, end, budget)` on a TIGHT window: use transcript segment
   timestamps verbatim — the cue's segment `start` as `start`, and a segment a little later as
   `end` (do no time arithmetic; copy the timestamps that appear in your transcript). Keep the
   per-cue budget small. `video_path` is the exact absolute path you were handed — use it verbatim.
4. **Backstop (only if told the topic is strongly visual).** If the orchestrator flagged this
   topic as strongly visual but step 2 found no explicit cues, take ONE light sample across the
   window — a single `select_keyframes` call with a small budget — so a silently-shown slide
   isn't missed.
5. **Read, then keep only what adds.** **Read** each candidate image and transcribe its useful
   on-screen content INTO the note text (a diagram's structure, a slide's points, on-screen
   code/formulas) — the note must stand alone without the images. Then
   `keep_frame(candidate_path, prefix, timestamp)` and embed with `![[<embed_path>]]` ONLY the few
   frames that add something the text cannot. Discard redundant or low-value candidates.
