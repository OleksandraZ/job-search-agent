"""Regression tests for pipeline/location.py.

Every case here is a real posting that once produced a wrong Munich/remote
classification (or a false positive that had to be guarded against) - see
docs/lessons/classification.md for the full incident behind each one. The point of
this file is that a future refactor of location.py can't silently reintroduce any of
these without a test failing; write the failing case into a fixture instead of just
narrating it in memory/docs next time.
"""

from adapters.boards import NormalizedJob
from pipeline.location import is_munich, is_remote


def _job(location: str = "", description: str = "") -> NormalizedJob:
    return NormalizedJob(
        source_id="test", title="Test Engineer", company="Test GmbH", url="https://example.test/1",
        location=location, description=description,
    )


# --- is_remote() ---


def test_is_remote_ignores_bare_word_matches_in_free_text():
    # Real GermanTechJobs posting (Nürnberg, hybrid): "Remote-Erstgespräch" is a
    # remote *interview* mention, "2 Tage pro Woche Homeoffice" is 2 days/week WFH -
    # hybrid, not full-remote. A bare "remote"/"homeoffice" substring match on this
    # text was the original bug (see phase2 memory).
    job = _job(
        location="Germany",
        description=(
            "Wir laden Sie zu einem Remote-Erstgespräch ein. Die Position ist "
            "grundsätzlich vor Ort in Nürnberg zu besetzen, 2 Tage pro Woche "
            "Homeoffice sind möglich."
        ),
    )
    assert is_remote(job) is False


def test_is_remote_respects_negation():
    # Real Arbeitnow posting: "not" immediately before "full remote" flips the
    # meaning - the job is explicitly hybrid, not remote.
    job = _job(
        location="Nürnberg",
        description="On-site availability in Nürnberg (hybrid, not full remote).",
    )
    assert is_remote(job) is False


def test_is_remote_rejects_remote_first_as_not_unambiguous():
    # Real TestDevJobs posting (akirolabs): the company's own definition of
    # "remote-first" explicitly included hybrid office work in Berlin, so it isn't
    # the same hard commitment as "100% remote"/"fully remote".
    job = _job(
        location="Berlin",
        description=(
            "Remote-first – work where you work best, whether from home or in a "
            "hybrid mode from our office in Berlin."
        ),
    )
    assert is_remote(job) is False


def test_is_remote_trusts_a_short_structured_location_field():
    # Arbeitnow-style: a short, deliberate location value the company set is
    # trusted more loosely than free-text description prose.
    job = _job(location="Fully Remote", description="")
    assert is_remote(job) is True


def test_is_remote_true_positive_unambiguous_german_phrase():
    # Real StepStone posting genuinely offering full remote work.
    job = _job(
        location="Deutschland",
        description="Diese Position ist komplett remote zu besetzen, deutschlandweit.",
    )
    assert is_remote(job) is True


# --- is_munich() ---


def test_is_munich_trusts_structured_location_over_hq_boilerplate_in_description():
    # Real StepStone posting: the job is in Kirchdorf an der Iller (near Ulm), but
    # its description opens with company-HQ boilerplate ("mit Sitz in ... München")
    # that a bare description scan would misread as the job's own location.
    job = _job(
        location="Kirchdorf an der Iller",
        description="Das Unternehmen mit Sitz in Taufkirchen bei München entwickelt seit über 20 Jahren...",
    )
    assert is_munich(job) is False


def test_is_munich_falls_back_to_description_only_for_placeholder_location():
    # GermanTechJobs has no real per-job location field - every job gets the
    # placeholder "Germany", so the description is the only signal available.
    job = _job(location="Germany", description="Standort: München, hybrides Arbeiten möglich.")
    assert is_munich(job) is True


def test_is_munich_trusts_a_real_structured_location_field():
    job = _job(location="München", description="")
    assert is_munich(job) is True


def test_is_munich_false_for_unrelated_structured_location():
    job = _job(location="Hamburg", description="")
    assert is_munich(job) is False
