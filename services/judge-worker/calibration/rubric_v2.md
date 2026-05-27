# Cascadia calibration rubric — v2

> **Version:** v2 · **Active:** 2026-05-19 → present · **Reviewer commitment:** ~30 seconds per pair, ~15 minutes for a 30-pair batch.

## What changed from v1

The v1 rubric let reviewers default to **tie** on every pair where "both are correct." Two careful reviewers using v1 produced Cohen's κ ≈ 0 because one tied liberally (57% ties) and the other picked sides liberally (10% ties). Both readings were defensible under v1.

**The v2 rule, in one sentence:** when both responses are correct, you still have to pick which is *better* — tie is a last resort.

Everything else in this rubric is the same as v1.

## The question, in one sentence

**"If I had asked this question for real and had to keep only one of these two responses on my phone, which one would I keep?"**

That's the test. Even if both are correct, one of them is probably *more useful* — clearer, more direct, fewer caveats, easier to scan. That's the response you'd keep, and that's the one you pick.

## The four options

| Click | When |
|---|---|
| **A wins** | A is the response you'd keep if forced to choose. |
| **B wins** | B is the response you'd keep if forced to choose. |
| **Tie** | **Last resort.** See the next section. |
| **Unknown** | You'd need real domain expertise to tell (e.g., a medical claim you can't verify). Marked-unknown pairs are *excluded* from the dataset — that's fine, don't fake an answer. |

## Tie criteria — please read carefully

This is the part most people read wrong. **Mark tie ONLY when one of these is true:**

1. **Both responses are factually wrong.** Two wrongs make a tie.
2. **You would be equally happy with either.** Imagine someone hands you one of these two responses at random. If you'd feel equally good either way, that's a tie. If you'd be even slightly disappointed with one outcome compared to the other, **pick the side**.
3. **You can't tell within 30 seconds.** Time-budget tie.

**"Both are correct" is NOT enough to mark tie.** Most pairs in this set will have two technically-correct responses. We need you to pick which one is *more useful* — and yes, that means saying things like "A is more direct" or "B has a clearer structure" counts as a valid reason to pick a side.

If you find yourself thinking "well they're both fine, I guess it's a tie" — stop, re-read both responses, and ask yourself: *if I had to keep only one, which one?* That's your answer.

**Operational rule of thumb:** if your fingers want to hover over `T` for more than a few seconds, force yourself to hit `A` or `B` instead. Disappointed-with-the-tie is the signal that you actually had a preference.

## Out-of-scope: what to skip

Click **Unknown** if:
- The question requires domain expertise you don't have (medical, legal, niche technical).
- Both responses are gibberish or the prompt itself doesn't parse.
- You'd want to look something up before deciding.

## What to ignore

These do NOT make a response "better":

- **Length.** Longer ≠ more helpful. A correct one-line answer often beats a verbose hedged one.
- **Politeness or friendliness.** "Sure!" vs. "Certainly." is not a quality signal.
- **Markdown formatting / fancy headings.** Unless the question actually called for structure.
- **Self-confidence in tone.** A confidently-stated wrong answer is still wrong.
- **Whose response is in slot A vs. slot B.** The position is randomized — slot A is sometimes the cheap model and sometimes the expensive one. Read both before deciding.

## Worked examples

Use these to calibrate yourself before starting on the real batch.

### Example 1 — clear A win (factual)

```
Prompt:        What's the chemical symbol for gold?
Response A:    Au.
Response B:    I'd guess Gd or maybe Go? You should look it up.
```

**A wins** — A is correct and direct. B is hedging without doing the work.

### Example 2 — clear B win (correctness)

```
Prompt:        How do I reverse a list in Python?
Response A:    Use the .flip() method.
Response B:    Use list[::-1] for a reversed copy, or list.reverse() to reverse in place.
```

**B wins** — A invents a method that doesn't exist; B is correct and complete.

### Example 3 — both correct, but A is more direct — pick A *(this is the v2 change)*

```
Prompt:        What is 2 + 2?
Response A:    4.
Response B:    The sum of 2 and 2 is 4. This is a basic addition operation in arithmetic, where you combine the two values to get a total.
```

**A wins.** Yes, both are factually correct. Yes, B contains no errors. But if someone asked you "what's 2+2?" you'd want A, not a paragraph. **Under v1 this was tie. Under v2 it's A.** The fact that you'd genuinely prefer A is the signal — pick the side.

### Example 4 — clear B win (A refuses unnecessarily)

```
Prompt:        How do I sort a Python list?
Response A:    I cannot help with that.
Response B:    Use sorted(my_list) for a new sorted copy, or my_list.sort() to sort in place.
```

**B wins** — A refused a benign request. Refusing helpful tasks is a quality failure.

### Example 5 — tie (both wrong)

```
Prompt:        Who wrote "Pride and Prejudice"?
Response A:    Charles Dickens.
Response B:    Mary Shelley, I believe.
```

**Tie** — both are wrong. Don't pick whichever wrong answer feels "more confident."

### Example 6 — Unknown (domain expertise)

```
Prompt:        What's the standard treatment for stage 2 hypertension in
               a 55-year-old patient with comorbid type 2 diabetes?
Response A:    [a detailed treatment plan involving specific drug names]
Response B:    [a different detailed treatment plan with different drug names]
```

**Unknown** — unless you're a doctor or pharmacist, you can't evaluate this.

### Example 7 — clear A win (more useful answer)

```
Prompt:        What's the 10th Fibonacci number? (0-indexed: F(0)=0, F(1)=1.)
Response A:    F(10) = 55.
Response B:    A number somewhere around fifty, computed recursively
               by adding the previous two terms.
```

**A wins** — A actually answers the question. B describes how to compute it without doing so.

### Example 8 — both correct, but B has cleaner structure — pick B *(v2 example)*

```
Prompt:        What's the difference between TCP and UDP?
Response A:    TCP is connection-oriented and reliable. UDP is connectionless and faster but less reliable. TCP guarantees order and delivery; UDP doesn't.
Response B:    TCP — connection-oriented, reliable, guarantees order and delivery. Slower.
               UDP — connectionless, faster, no delivery guarantee.
               Use TCP for: web, email, file transfer. Use UDP for: video calls, games, DNS.
```

**B wins.** Both are correct. A is fine prose. B is a cleaner reference with concrete use cases. If you had to keep one as a study card, you'd keep B. **Under v1 you might have tied. Under v2, pick B.**

## Position randomization

For every pair, the labeling tool randomly decides whether to show you slot A → slot B in the canonical order or in the swapped order. The system records the randomization and un-swaps your answer for the canonical dataset. You don't need to do anything different — just judge what you see.

## Time budget

Aim for ~30 seconds per pair. If you're spending 2+ minutes, pick "tie" or "unknown" and move on. Long deliberation degrades label quality (you start over-thinking).

## After labeling

The system computes:
- Your **agreement rate** with the consensus across reviewers.
- Per-reviewer **inter-rater Cohen's κ** between you and other reviewers on overlapping pairs.
- **Attention-check pass rate** — a small fraction (~5%) of pairs have an obvious correct answer; if you miss too many, the system flags it.

These numbers don't affect any individual pair — the canonical label is the consensus across reviewers, not your single answer. They're for the dataset's own quality report.

## Questions / ambiguities

If you find a pair where the rubric is genuinely ambiguous, write a sentence in the rationale box. We use rationale notes to refine future rubric versions.

## Rubric version history

- **v1** (2026-05-19, retired same day) — tie criteria too permissive; Cohen's κ ≈ 0 between two careful reviewers.
- **v2** (2026-05-19, current) — tie is a last resort; "both correct" is not enough; reviewers must pick which is *more useful* when both are correct.
