from pathlib import Path

import pytest
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# A hand-edited multi-line plain scalar (e.g. a sources.yaml `notes:` field) breaks
# the whole file as soon as it contains ": " - and nothing else in the test suite
# loads sources.yaml, so a broken file would only surface as a crashed daily run.
@pytest.mark.parametrize("path", sorted(CONFIG_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_config_file_is_valid_yaml(path):
    assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None
