"""Tests for pipeline/classify_language.py against config/language_rules.yaml's real
patterns and thresholds - see job_search_agent_phase4/phase5 memory and
docs/lessons/classification.md for the incidents behind each case.
"""

from pipeline.classify_language import is_german_required, split_by_language
from tests.conftest import make_job


def test_explicit_german_cefr_requirement_is_german():
    job = make_job(description="Verhandlungssichere Deutschkenntnisse sind erforderlich.")
    assert is_german_required(job) is True


def test_disclaimer_immediately_after_requirement_voids_it():
    # "von Vorteil" right after the CEFR match, same clause -> not a real requirement.
    job = make_job(description="Deutschkenntnisse B2 von Vorteil, aber nicht zwingend.")
    assert is_german_required(job) is False


def test_disclaimer_across_a_clause_boundary_does_not_apply():
    # "von Vorteil" is real text later in the description, but a '.' sits between it
    # and the requirement match - the disclaimer window is clause-bounded and must not
    # cross it.
    job = make_job(description="Deutschkenntnisse (B2). Andere Skills sind von Vorteil, wie Excel.")
    assert is_german_required(job) is True


def test_english_mention_before_disclaimer_means_disclaimer_applies_to_english():
    # The disclaimer applies to "Englisch", not the German requirement right before
    # it - the German match still counts.
    job = make_job(description="Gute Deutschkenntnisse, Englisch von Vorteil.")
    assert is_german_required(job) is True


def test_predominantly_german_description_with_no_explicit_statement_is_german():
    # No CEFR/fluent/native phrase anywhere - only the whole-description stopword
    # fallback can catch this.
    text = (
        "Der die das und mit für ist sich eine einen einer werden wir auf von "
        "nicht oder auch sind du deine dein unser unsere."
    )
    job = make_job(description=text)
    assert is_german_required(job) is True


def test_empty_description_defaults_to_english():
    # Documented gotcha (CLAUDE.md): a source that never fills in `description`
    # silently lands in the English bucket.
    job = make_job(description="")
    assert is_german_required(job) is False


def test_split_by_language_partitions_jobs():
    german_job = make_job(url="https://example.test/de", description="Fließende Deutschkenntnisse.")
    english_job = make_job(url="https://example.test/en", description="We are looking for a QA engineer.")

    german, english = split_by_language([german_job, english_job])

    assert german == [german_job]
    assert english == [english_job]
