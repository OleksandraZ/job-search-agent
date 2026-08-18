# Lessons: location and language classification

Full incident narratives behind `pipeline/location.py` and
`pipeline/classify_language.py`, referenced from the tight gotcha list in
`CLAUDE.md`. Each section leads with the rule and why it exists — keep reading past
that only if you want the real posting and root cause behind it. The common thread:
free-text `description`/`location` matching requires strong, unambiguous phrases
rather than bare words, has to stay within one clause, and isn't safe from negation —
every bug below is a variant of trusting a pattern match more than the surrounding
text actually supported.

## <a name="unambiguous-phrases"></a>Bare `remote`/`homeoffice` substring match was a false positive

**Require an unambiguous phrase, never a bare word, for free-text remote matching.**
A bare word is too easy to trigger on something adjacent to the real arrangement —
an interview format, a partial WFH allowance — rather than the job itself.

A bare substring match misclassified a hybrid Nürnberg job as remote — it matched
"Remote-Erstgespräch" (a remote *interview* mention) and "2 Tage Homeoffice" (hybrid,
not full-remote). Fixed by requiring unambiguous phrases (`100% remote`,
`fully remote`) in free text, while still trusting a source's short, structured
`location` field more loosely (see `LOCATION_REMOTE_PATTERN` vs
`DESCRIPTION_REMOTE_PATTERN` in `pipeline/location.py`).

## <a name="clause-bounded-gaps"></a>Word-gaps must stay inside one clause, not bleed across bullet points

**Bound every word-gap to one clause** (`[^.;<]`, stopping at sentence punctuation
*and* HTML tag boundaries). Descriptions are HTML with `<li>` bullet points; an
unbounded gap lets a disclaimer or requirement in one bullet silently apply to an
unrelated match in the next one.

This was found when an unbounded gap let a disclaimer phrase ("von Vorteil") in one
bullet point falsely negate a real requirement match in an unrelated adjacent one.
Before adding or loosening a pattern here, validate it against real fetched
description text first (not written from assumption) — see `job_search_agent_phase4`
memory for the specific false-positive cases this ruled out, including one where the
exact same surface phrase ("gute Deutschkenntnisse") means opposite things depending
on what immediately follows it.

## <a name="negation-check"></a>Even an "unambiguous phrase" match isn't safe from negation

**Check the clause immediately before a phrase match for negation words** (`not`,
`nicht`, `kein(e)`, `no longer`), not just whether the phrase itself appears. An
unambiguous phrase can still be negated by what comes right before it.

A real Arbeitnow posting read "hybrid, not full remote" — "full remote" matched
`DESCRIPTION_REMOTE_PATTERN` as a phrase, but "not" right before it flips the meaning
entirely, and nothing checked for that. `pipeline/location.py:is_remote()` now checks
the clause immediately *before* a match using the same clause-bounded-window
technique as the disclaimer check above, just looking backward. Check both
directions — what precedes and what follows — before trusting any new regex
classifier here.

## <a name="is-munich-fallback"></a>`is_munich()`'s free-text fallback is gated on the source having no real location field

**Once a source has a real, structured `location`, trust it exclusively** — don't
also scan free-text `description` for a city name. Company boilerplate in the
description (an "about us" opener, an HQ address) can mention a city that has
nothing to do with where the job actually is.

A real StepStone posting for a Kirchdorf an der Iller (near Ulm) role was
misclassified as Munich because its description's standard company-boilerplate
opener ("Das Unternehmen mit Sitz in Taufkirchen bei München...") mentions the
company's *HQ city*, not the job's actual location — and that same "mit Sitz in
&lt;city&gt;" opener recurs across unrelated StepStone postings regardless of where
the role itself is, so it wasn't a one-off. Fix: `is_munich()` now only falls back to
scanning `description` when `location` is empty or a known no-data placeholder
(`GENERIC_LOCATION_PLACEHOLDERS = {"germany", "deutschland"}`, i.e. GermanTechJobs).
Adding a source with substantial free-text company-boilerplate in `description` is
exactly when this class of bug resurfaces — re-check it.

## <a name="phrase-generalization"></a>Not every "unambiguous" phrase stays unambiguous as more sources arrive

**Re-validate every existing pattern against each new source's real fetched text** —
a phrase that was a hard commitment on one source can turn out to be softer on the
next one.

`remote[\s-]?first` was removed from `DESCRIPTION_REMOTE_PATTERN` after a real
TestDevJobs posting read "Remote-first – work where you work best, whether from home
or in a hybrid mode from our office ... in Berlin" — the company's own definition of
"remote-first" there explicitly included hybrid office work, so it isn't the same
kind of hard commitment as "100% remote"/"fully remote". A phrase added against one
source's real data isn't guaranteed to generalize to the next source's usage of it.

## <a name="english-german-signals"></a>German-requirement signals also show up phrased in English

**Check for a requirement phrased in English too, not just German prose** — and
check the disclaimer list in both languages symmetrically, or a real disclaimer in
one language won't cancel a false match caused by the other.

`config/language_rules.yaml`'s `german_required_patterns` originally only matched
German words (`Deutschkenntnisse`, CEFR-level-near-`deutsch`, etc.); real DEVjobs.de
text (which auto-translates German-origin postings to English) and EnglishJobs.de
text (an English-first board that still lists some German-requiring roles) surfaced
real, stated requirements phrased entirely in English that nothing caught: "Good
knowledge of German and English.", "Very good written and spoken German and English
skills.", "fluency in German and English" (a different word stem than "fluent" —
`\bfluen\w*`, not `fluent\w*`, is needed to catch both). Symmetrically,
`optional_disclaimer_patterns` was German-phrase-only (`von Vorteil`,
`wünschenswert`, ...) — a real "Fluent English skills and German as a plus." posting
was wrongly counted as German-required because there was no English disclaimer to
cancel it (`a plus`, `desirable`, `nice to have`, `not required`/`not mandatory` were
added) — see `job_search_agent_phase5` memory for the exact false-positive/negative
cases this ruled out.

## <a name="whole-description-german"></a>A posting can require German without ever *stating* it does

**A description that's predominantly German prose is itself evidence of the
requirement**, even with no explicit "German required" statement anywhere —
`is_german_required()` has a calibrated stopword-frequency fallback for this,
triggered only when explicit-phrase matching finds nothing.

Every explicit pattern looks for a requirement phrase — but a real Instaffo posting
(and, checking after the fact, an already-sent XING one) was 100% German prose front
to back with no self-referential "Deutschkenntnisse required" statement anywhere,
since the platform's own market is German and stating the obvious would be
redundant. Both defaulted to the English bucket, undetected until the Instaffo round
was reviewed before its real send. Fix: `is_german_required()`'s second check
(`_is_predominantly_german()`, `config/language_rules.yaml`'s
`whole_description_language_signal`) was calibrated against real fetched samples
before wiring in (3 pure-German postings scored 0.91-0.94 German-word ratio; a
genuinely English Built In posting scored 0.00) — thresholds have wide margin on
both sides. This is a deliberate, narrow exception to "requires, not written in" (see
`job_search_agent_plan.md` §8).

**When building a true-negative test sample for this kind of check, verify it's
actually negative.** An initial "clean English" calibration sample turned out to
genuinely require German, just stated in English prose ("Very good English and
German language skills are a prerequisite") — a true positive via the *existing*
explicit-phrase path, not a bug in the new whole-description code. Don't assume a
mismatch during calibration is a regression before checking which path produced it.
