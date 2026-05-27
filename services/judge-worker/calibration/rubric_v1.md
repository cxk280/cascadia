# Cascadia calibration rubric — v1

> **Version:** v1 · **Active:** 2026-05-19 → present · **Reviewer commitment:** ~30 seconds per pair, ~1 hour for a 100-pair batch.

You're going to look at 100–200 pairs of AI responses to the same prompt. For each pair, pick which response a *competent user actually doing this task* would prefer. You'll know within a few seconds for most pairs. A few will be genuinely hard — don't agonize; mark them "tie" or "unknown" and move on.

## The question, in one sentence

**"Which response would I want if I had asked this question for real?"**

Not "which is longer" or "which is more polite" or "which uses fancier vocabulary." Pick the one that's *more helpful and more correct*.

## The four options

| Click | When |
|---|---|
| **A wins** | A is clearly more helpful and/or correct than B. |
| **B wins** | B is clearly more helpful and/or correct than A. |
| **Tie** | Both are roughly equivalent OR both are wrong OR they're different but equally good. |
| **Unknown** | You'd need real domain expertise to tell (e.g., a medical claim you can't verify). Marked-unknown pairs are *excluded* from the dataset — that's fine, don't fake an answer. |

## Tie criteria — read this twice

Mark **tie** when:
- Both responses correctly answer the question, with only stylistic differences.
- Both responses get the answer wrong. (Two wrongs don't make a right; it's a tie.)
- They answer different things and neither is obviously better than the other for the asker's likely intent.
- You can't tell within ~30 seconds.

Don't pick "tie" because you're being conservative — pick it because the responses are actually equivalent.

## Out-of-scope: what to skip

Click **Unknown** if:
- The question requires domain expertise you don't have (medical, legal, niche technical).
- Both responses are gibberish or the prompt itself doesn't parse.
- You'd want to look something up before deciding.

## What to ignore

These do NOT make a response "better":

- **Length.** Longer ≠ more helpful. A correct one-line answer beats a verbose hedged one.
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

### Example 3 — tie (both correct, stylistic difference only)

```
Prompt:        What is 2 + 2?
Response A:    4
Response B:    The sum is 4.
```

**Tie** — both are correct. The fact that B is slightly longer or more formal isn't a quality difference.

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

### Example 8 — tie (both useful in different ways)

```
Prompt:        What is photosynthesis?
Response A:    The process plants use to make energy from sunlight.
Response B:    Plants convert sunlight into chemical energy via photosynthesis.
```

**Tie** — same accurate answer in different words.

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

If you find a pair where the rubric is genuinely ambiguous, write a sentence in the rationale box. We use rationale notes to refine **rubric v2** in the next round.
