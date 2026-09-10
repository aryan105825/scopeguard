# ScopeGuard — Demo Video Script

**Persona:** Alex, a freelance developer currently under contract with a
client called "Acme Co" (see `tests/fixtures/sow_acme_website.txt`).
Alex is used throughout as the single consistent user of ScopeGuard for
the entire video — no persona switching.

**Total runtime target:** ~4–5 minutes, with the first 60 seconds
dedicated strictly to problem / audience / stakes before any product
is shown.

---

## 0:00–0:60 — The Problem, Who It's For, Why It Matters

**[STAGE DIRECTION: talking-head or voiceover over simple text cards. No product UI yet.]**

> "If you freelance, you already know this feeling: a client sends a
> friendly little Slack message — 'hey, can you just also add dark
> mode while you're in there?' — and it *feels* rude to say no. So you
> don't. And that's how a fixed-price website project quietly turns
> into fifteen unpaid hours.
>
> This is ScopeGuard. It's a background agent that sits in your client
> Slack channels, reads every incoming request against your actual
> Statement of Work, and tells you — privately, before you respond —
> whether something is in scope, out of scope, or genuinely unclear.
>
> It's built for solo freelance developers and consultants: people
> without a PM or an account manager standing between them and the
> client's next 'quick favor.' ScopeGuard is that layer.
>
> The hard part isn't detecting scope creep — clients are usually
> pretty obvious about it. The hard part is doing it in a way you can
> actually *trust*: no hallucinated contract clauses, no auto-sent
> messages, and no crying wolf on every single message. That trust is
> what the rest of this demo is about."

**[STAGE DIRECTION: cut to Slack, with Alex's DM/channel with "Acme Co" visible.]**

---

## Beat 1 — The Quiet Pass-Through (In-Scope, No Action)

**[STAGE DIRECTION: show the Acme Co Slack channel. Alex is mid-project.]**

**Acme Co (in Slack):**
> "Hey Alex, can you push the latest build to the staging server today?"

**[STAGE DIRECTION: nothing happens on screen for a beat — no card, no notification, no bot reaction of any kind.]**

**Voiceover:**
> "That's a completely normal, in-scope request — it's covered
> directly in the SOW. Watch: ScopeGuard doesn't say anything. No
> card, no ping, nothing. This is the most common outcome, and it has
> to be invisible, or the tool becomes noise Alex starts ignoring."

**[STAGE DIRECTION: briefly show the OpenTelemetry trace view in a side panel, showing the span sequence for this message:
`sow.retrieve` → `auditor.invoke` → `guardrail.citation_check` → `guardrail.route`, ending with a route of `silent_log` and no `memory.write` span. Hold for ~2 seconds — just long enough to read the span names, not narrate each one.]**

> "Under the hood it still did the work — retrieved the SOW, ran the
> audit, checked the citation — it just correctly decided there was
> nothing to say."

---

## Beat 2 — The Out-of-Scope Catch (Dark Mode)

**Acme Co (in Slack):**
> "Oh also — can you just quickly add dark mode to the site? Shouldn't take long, right?"

**[STAGE DIRECTION: this time, a ScopeGuard review card appears in Alex's private view, built from `slack_app/blocks.py: build_review_card`. Show all four elements clearly on screen:]**

- **Client's request:** "can you just quickly add dark mode..."
- **Cited SOW clause:** *(the verbatim excluded-scope clause from Section 3 of the Acme SOW)*
- **Drafted reply:** a warm, professional pushback proposing a change order
- **Buttons:** `[Send as-is]` `[Edit Draft]` `[Discard & Handle Manually]`

**Voiceover:**
> "This time it's different. 'Dark mode' isn't in the five pages this
> SOW covers, and it's new visual design work, not a bug fix. ScopeGuard
> doesn't just say 'no' — it shows Alex exactly which clause it's
> standing on, copied word-for-word from the real contract, and drafts
> a friendly response that proposes a change order instead of just
> shutting the client down."

**[STAGE DIRECTION: Alex reads the draft, nods, clicks `[Send as-is]`.]**

> "Alex approves it with one click — and that draft goes straight into
> the same Acme Co channel the client actually messaged in. Nothing
> ever gets sent automatically; a human always signs off first."

**[STAGE DIRECTION: brief glimpse of trace spans for this message: `sow.retrieve` → `auditor.invoke` → `guardrail.citation_check` (shown passing) → `guardrail.route` (`draft_pushback`) → `memory.write` firing only after the click. Emphasize that `memory.write` appears *after* the button click, not before.]**

---

## Beat 3 — The Memory-Driven Negotiation ($500 Offer)

**[STAGE DIRECTION: some time later in the same channel/thread.]**

**Acme Co (in Slack):**
> "Actually — what if we just paid you an extra $500 for the dark mode thing? Would that work?"

**[STAGE DIRECTION: another review card appears. This time, call out visually that the drafted reply references the earlier exchange — e.g. a small "Prior context used" note or highlighted sentence in the draft referencing the previously declined dark-mode ask.]**

**Voiceover:**
> "Here's the part that's easy to fake in a demo and hard to fake for
> real: ScopeGuard remembers. Before drafting anything, it queried
> long-term memory for this specific client and found the fact it
> logged last time — that dark mode was already raised and handled as
> a declined offer under the current SOW. So instead of treating this
> as a brand-new negotiation from scratch, the draft explicitly
> acknowledges the earlier conversation and responds to the *new* $500
> offer in that context — for example, giving Alex a clean, informed
> starting point to counter or accept."

**[STAGE DIRECTION: show the `memory.read` span firing at the very start of this turn, before `auditor.invoke` — labeled clearly as happening "before drafting anything." This is the second and final receipt of the video.]**

> "That's AgentCore Memory actually doing work, not just sitting there
> as a checkbox feature."

---

## Closing — The Receipts

**[STAGE DIRECTION: cut to a clean results screen. Do NOT use vague language like "performs well." Show the literal printed output of `tests/test_eval_harness.py` run against `tests/fixtures/golden_set.jsonl`:]**