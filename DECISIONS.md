# DECISIONS

**1. At episode 150, what is in context and what is retrieved or summarized?**
The writer never sees the raw story. Every episode gets a fixed-size packet of about 3-4k tokens, the same size at episode 150 as at 15.
- **Always in context:** series bible (tone, POV, world rules), current act and segment goal, the beat for this episode plus 2 before and 3 after, and every active human directive.
- **Summarized:** the last 5 episode summaries, the last 2 ten-episode chapter summaries, and a story-so-far capped at ~450 words and refolded every 10 episodes. The last ~250 words of episode 149 go in verbatim, so voice and the cliffhanger carry over.
- **Queried from Postgres:** up to 8 character cards in play, the full list of dead or missing characters, up to 8 open threads (overdue first, then longest idle), and up to 12 high-importance facts.
- **Retrieved from Qdrant:** the top 8 older summaries and facts that match this beat.

Structured memory (SQL) is the source of truth for things that must never be wrong, such as who is dead or what is overdue. Vectors are only for recall.

**2. Where does the human step in, and why there?**
- **Plan review, before any writing:** this is the cheapest place to change the story, since editing a beat costs nothing.
- **Episode review:** approval is the moment text becomes canon and enters memory. It comes after the critic, so the human sees fewer bad drafts. In auto-approve batches this step is skipped only when the critic passes; flagged episodes always stop for review.
- **Continue gate between batches:** this is the stop/resume point and where the budget cap pauses the run.

Feedback like "slow down the romance" becomes a standing directive that goes into every later writer and critic prompt, and the critic enforces it. It also rewrites the next 15 beats, bumping the plan version. It is not a one-off prompt note. Directives can be retired from the Story bible panel.

**3. How are inconsistency and repetition caught before the human sees them?**
Three layers run, cheapest first:
1. **Deterministic checks:** word count between 400 and 700, 6-gram overlap above 6% with the last 3 episodes, banned clichés, and dead characters mentioned.
2. **LLM critic:** it sees the same context packet as the writer and returns a hook score (≥7 to pass), a beat-adherence score (≥6 to pass), and typed issues (continuity, directive, repetition) with severity.
3. **Embedding check:** the episode's beat summary is compared against all past beats, and cosine ≥0.90 means the episode repeats one already written.

A failing draft is revised at most 2 times, capped at $0.05 per episode, then escalated to the human with the reason. The whole story has a $5 cap that pauses the run.

**Retroactive edit (e.g. episode 40 changes):** character state is event-sourced. Episode 40's facts, thread changes and vectors are deleted and re-extracted from the new text, and affected characters are rebuilt by replaying their events. The affected summaries are rebuilt too. An LLM ripple check then lists specific conflicts in up to 30 later episodes, such as "episode 47 holds Theo's funeral". Future episodes use the corrected memory automatically; existing ones are flagged, not silently rewritten.

**4. What breaks first, and how to fix it?**
- **Summary drift.** Refolding the story-so-far loses detail over 200 episodes. Fix: facts and threads are stored separately and never summarized away. Next step is to rebuild the story-so-far from all chapter summaries rather than from the previous fold.
- **Plan drift.** Beats written on day 1 stop matching what actually happened. Fix: re-expand the next segment's beats from the real story at each segment boundary.
- **Critic bias.** A critic running on the same model as the writer tends to approve its own style. Fix: use a different model family for the critic (one environment variable) and calibrate thresholds against logged human decisions.
- **Throughput.** Groq's free-tier per-model limit (8k tokens/min) binds long before cost does. The single-process runner is the next limit after that. Fix: a queue with workers and Postgres advisory locks. Checkpoints already live in Postgres, so any worker can resume any story.

**Cost:** writing runs on gpt-oss-120b and checking/memory on gpt-oss-20b. Measured per episode: about 16k input and 3.2k output tokens, reasoning included, which is roughly **$0.004 per episode, or $0.80-1.00 for 200** with planning; verify current Groq pricing. On Groq's free tier it costs $0, and **time** is the cost. Each model allows 8k tokens/min, so 200 episodes take about **4.5-5 hours** (~1.3 min per episode on the 20b quota), against ~35-50 minutes unthrottled. The live projection in Story bible → Trace includes rate-limit waits.

To reduce cost and time:
- Stop forced revisions. Drafts measured 748-757 words against the 700 cap, which triggers a rewrite costing ~35% of an episode. Ask for 500-600 words.
- Skip the LLM critic when the deterministic checks are clean in auto batches (critiques are ~80% of the 20b tokens).
- Move the writer to gpt-oss-20b (~30% cheaper, some quality loss).
- Cache the static prompt prefix, and batch extraction.
