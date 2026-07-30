from importlib.util import find_spec
from pathlib import Path

import pytest

from openams.io import (
    InputError,
    SerializationDependencyError,
    load_yaml_mapping,
)


def test_yaml_dependency_is_isolated(tmp_path: Path) -> None:
    source = tmp_path / "document.yaml"
    source.write_text("name: openams\n", encoding="utf-8")

    if find_spec("yaml") is None:
        with pytest.raises(SerializationDependencyError, match="PyYAML"):
            load_yaml_mapping(source)
    else:
        assert load_yaml_mapping(source) == {"name": "openams"}


@pytest.mark.skipif(find_spec("yaml") is None, reason="PyYAML is not installed")
def test_yaml_root_must_be_mapping(tmp_path: Path) -> None:
    source = tmp_path / "document.yaml"
    source.write_text("- one\n- two\n", encoding="utf-8")

    with pytest.raises(InputError, match="root must be a mapping"):
        load_yaml_mapping(source)
