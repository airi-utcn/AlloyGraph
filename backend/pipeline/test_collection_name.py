import pytest

from backend.pipeline.weaviate_ingest import collection_name

class Cfg1:
    _name = "Material"

class Cfg2:
    name = "Variant"

class Col1:
    config = Cfg1()

class Col2:
    config = Cfg2()

class Col3:
    _name = "Composition"

class Col4:
    def __str__(self):
        return "StrCol"

class BadCol:
    def __str__(self):
        raise RuntimeError("boom")


def test_config__name():
    assert collection_name(Col1()) == "Material"


def test_config_name():
    assert collection_name(Col2()) == "Variant"


def test_col__name():
    assert collection_name(Col3()) == "Composition"


def test_str_fallback():
    assert collection_name(Col4()) == "StrCol"


def test_bad_str():
    assert collection_name(BadCol()) == "<unknown-collection>"

