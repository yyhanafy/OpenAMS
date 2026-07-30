import openams


def test_package_import() -> None:
    assert openams.__version__ == "0.1.0"
