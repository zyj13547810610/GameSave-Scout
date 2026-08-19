def test_package_exposes_version() -> None:
    import gameshelf

    assert gameshelf.__version__ == "0.2.1"
