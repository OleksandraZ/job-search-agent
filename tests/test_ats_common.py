from adapters.ats._common import is_germany_relevant


def test_recognizes_a_german_city():
    assert is_germany_relevant("Berlin") is True


def test_recognizes_germany_by_name():
    assert is_germany_relevant("Remote - Germany") is True


def test_rejects_a_non_germany_city():
    assert is_germany_relevant("Barcelona") is False


def test_rejects_a_non_germany_country():
    assert is_germany_relevant("Remote - Spain") is False


def test_ambiguous_bare_remote_defaults_to_relevant():
    assert is_germany_relevant("Remote") is True


def test_empty_location_defaults_to_relevant():
    assert is_germany_relevant("") is True
