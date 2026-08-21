---
name: edit-classification
description: Add or change a pattern in pipeline/location.py (is_munich/is_remote) or pipeline/classify_language.py (is_german_required) — new regex, new phrase, new source-specific carve-out, or a threshold in config/language_rules.yaml. Use before touching either file, not after, since every past bug here was a real false positive/negative that shipped first and got caught later.
---

# Edit location or language classification

Both files do free-text matching against real job descriptions, and every existing
guard in them (clause bounds, negation checks, structured-field gating) exists
because a real posting broke an earlier, more naive version. Read
`docs/lessons/classification.md` in full before editing either file — each section
below is a rule from there; the doc has the real posting text and root cause for
each. Don't add or loosen a pattern from assumption about how postings are usually
phrased — validate against real fetched text (step 1) every time.

## 1. Pull real fetched text before writing or changing any pattern

Don't write a new regex against imagined phrasing. Get real `description`/`location`
text from an actual source first:

```python
.venv/bin/python -c "
from adapters.registry import fetch_from_sources
import yaml
sources = yaml.safe_load(open('config/sources.yaml'))
keywords = yaml.safe_load(open('config/keywords.yaml'))
jobs = fetch_from_sources(sources, keywords, ['<source_id>'])
for j in jobs[:5]:
    print(j.location, '|', j.description[:300])
"
```

If you're changing an existing pattern because a specific job was misclassified,
start from that job's actual `description`/`location`, not a paraphrase of it — the
Kirchdorf/Taufkirchen and "hybrid, not full remote" bugs (see the lesson doc) both
turned on exact wording a paraphrase would have smoothed over.

## 2. Free-text matching needs an unambiguous phrase, not a bare word

[`docs/lessons/classification.md#unambiguous-phrases`](../../../docs/lessons/classification.md#unambiguous-phrases) —
a bare `remote`/`homeoffice` substring match caught "Remote-Erstgespräch" (an
interview format) and "2 Tage Homeoffice" (hybrid). `DESCRIPTION_REMOTE_PATTERN` in
`pipeline/location.py` only matches hard commitments (`100% remote`,
`fully remote`, `remote only`, ...) — a bare `location` field is the one exception,
gated separately (see `LOCATION_REMOTE_PATTERN`), because a short structured field a
company set themselves doesn't carry the same ambiguity risk as prose. If you're
adding a new phrase, ask: does this phrase ever show up in a context that isn't a
full commitment? If yes, it doesn't belong in the strict pattern.

## 3. Bound every word-gap to one clause

[`docs/lessons/classification.md#clause-bounded-gaps`](../../../docs/lessons/classification.md#clause-bounded-gaps) —
descriptions are HTML with `<li>` bullets; an unbounded gap lets a disclaimer or
requirement in one bullet apply to an unrelated match in the next. Both files already
have this machinery — reuse it, don't re-derive it: `pipeline/location.py`'s
`_preceding_clause()`/`CLAUSE_BOUNDARY` and `pipeline/classify_language.py`'s
`_same_clause()`/`CLAUSE_BOUNDARY` both stop at `[.;<]`. Any new lookahead/lookbehind
window needs the same stop set, not a raw `.{0,N}` regex gap.

## 4. Check for negation immediately before a phrase match, not just the match itself

[`docs/lessons/classification.md#negation-check`](../../../docs/lessons/classification.md#negation-check) —
a real posting read "hybrid, not full remote"; "full remote" matched the phrase
pattern but "not" right before it flips the meaning. Check both directions —
`pipeline/location.py:is_remote()` checks the clause *before* a match
(`NEGATION_PATTERN` against `_preceding_clause()`); `classify_language.py`'s
disclaimer check looks *after* a match for the same reason. A new pattern in either
file needs the same treatment: don't trust a phrase match without checking the
clause immediately adjacent to it for something that reverses it.

## 5. Trust a real structured `location` exclusively once one exists — don't also scan free text

[`docs/lessons/classification.md#is-munich-fallback`](../../../docs/lessons/classification.md#is-munich-fallback) —
a StepStone posting for a Kirchdorf an der Iller role was misclassified as Munich
because its description's boilerplate opener named the company's HQ city, not the
job's location. `is_munich()` only falls back to scanning `description` when
`location` is empty or in `GENERIC_LOCATION_PLACEHOLDERS`. If you're adding a source
with a real structured `location` field, don't add description-scanning for it "just
in case" — that's exactly the false-positive class this guards against.

## 6. Re-validate every existing pattern against the new source's real fetched text

[`docs/lessons/classification.md#phrase-generalization`](../../../docs/lessons/classification.md#phrase-generalization) —
`remote[\s-]?first` was removed after a TestDevJobs posting used it to mean hybrid,
not a full-remote commitment. A phrase that was unambiguous on the sources it was
validated against isn't guaranteed to stay that way on a new one — re-run step 1
against the new source specifically, don't assume the existing pattern set transfers.

## 7. Check for the requirement phrased in English too, and disclaimers in both languages

[`docs/lessons/classification.md#english-german-signals`](../../../docs/lessons/classification.md#english-german-signals) —
`config/language_rules.yaml`'s `german_required_patterns` originally only matched
German phrasing; real postings stated the requirement entirely in English ("Good
knowledge of German and English", "fluency in German and English" — note `\bfluen\w*`,
not `fluent\w*`, to catch both). `optional_disclaimer_patterns` needs the same
symmetry — a German-only disclaimer list won't cancel a false match caused by an
English-phrased mention (`a plus`, `desirable`, `nice to have`,
`not required`/`not mandatory` exist for this). Adding a German-only pattern without
its English equivalent (or vice versa) reintroduces this gap.

## 8. Check whether the whole posting is predominantly German with no explicit statement at all

[`docs/lessons/classification.md#whole-description-german`](../../../docs/lessons/classification.md#whole-description-german) —
a real Instaffo posting was 100% German prose with no self-referential "German
required" statement anywhere (the platform's own market is German, so stating the
obvious would be redundant). `is_german_required()`'s explicit-phrase check can't
catch this by design — it needs `_is_predominantly_german()`'s stopword-ratio
fallback in `config/language_rules.yaml`'s `whole_description_language_signal`.
If you're touching the threshold (`min_german_words`/`min_ratio`), recalibrate
against real samples the way the original thresholds were (3 pure-German postings
scored 0.91–0.94, a genuine English posting scored 0.00 — wide margin on both sides)
— don't just eyeball a number. Also: verify your "clean English" calibration sample
is actually clean before trusting a mismatch as a bug — one such sample turned out to
genuinely require German, stated in English prose, which was the *existing*
explicit-phrase path working correctly, not a regression.

## 9. Test against real classification output, not just that the code runs

A pattern change can be syntactically fine and still be wrong. Run both checks
against real fetched jobs before considering the change done:

```python
.venv/bin/python -c "
from pipeline import classify_language, location
from adapters.registry import fetch_from_sources
import yaml
sources = yaml.safe_load(open('config/sources.yaml'))
keywords = yaml.safe_load(open('config/keywords.yaml'))
jobs = fetch_from_sources(sources, keywords, ['<source_id>'])
german, english = classify_language.split_by_language(jobs)
print('german=%d english=%d munich=%d remote=%d' % (
    len(german), len(english),
    sum(location.is_munich(j) for j in jobs),
    sum(location.is_remote(j) for j in jobs),
))
"
```

Spot-check a few individual jobs on each side of the split against their real
`description` text — a count that "looks plausible" isn't proof the specific jobs
landed in the right bucket. If you changed a pattern to fix one known
misclassification, confirm that specific job now lands correctly, then also re-check
a sample of jobs that were already classified correctly before your change, to catch
a fix that overcorrects into a new false positive/negative elsewhere.

## 10. Run the existing test suite and lint before finishing

`tests/test_location.py` and `tests/test_classify_language.py` encode the past
false-positive/negative cases from the lesson doc as regression tests — a change that
breaks one of them is very likely reintroducing a bug that already shipped once.
`ruff check .` and `mypy .` must show no errors (per `CLAUDE.md`).
