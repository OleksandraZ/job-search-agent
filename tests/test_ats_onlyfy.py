from adapters.ats import onlyfy_scrape
from tests.conftest import fake_response

LISTING_HTML = """
<a data-testid="job-card" href="/en/job/aaa">
  <h3 data-testid="job-title">Senior Engineer (m/w/d)</h3>
  <div data-testid="job-more-info">Munich | Full-time employee</div>
</a>
<a data-testid="job-card" href="/en/job/bbb">
  <h3 data-testid="job-title">Thermal Trainee</h3>
  <div data-testid="job-more-info">Hefei | Full-time employee</div>
</a>
"""


def test_keeps_only_recognized_german_cities_no_default_true_bias(monkeypatch):
    # Regression test: this adapter must use the *strict* location.py variant, not
    # is_germany_relevant()'s default-true-on-ambiguous bias - an earlier version
    # mislabeled "Hefei" (a real city in China, present on a real company's board
    # alongside Munich) as "Hefei, Germany" by defaulting an unrecognized city to
    # Germany-relevant.
    monkeypatch.setattr(
        onlyfy_scrape, "get_with_retry", lambda *a, **k: fake_response(text=LISTING_HTML)
    )

    jobs = onlyfy_scrape.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Engineer (m/w/d)"
    assert job.location == "Munich, Germany"
    assert job.url == "https://acme.onlyfy.jobs/en/job/aaa"
    assert job.description == ""
