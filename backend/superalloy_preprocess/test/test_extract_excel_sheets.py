import os
import json
import pytest
from backend.superalloy_preprocess import extract_excel_sheets

@pytest.fixture(scope="module")
def output_path():
    return extract_excel_sheets.OUTPUT_PATH

def test_extract_all_alloys_to_jsonl(output_path):
    if os.path.exists(output_path):
        os.remove(output_path)
    extract_excel_sheets.extract_all_alloys_to_jsonl()
    assert os.path.exists(output_path)
    with open(output_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    assert len(lines) > 0
    for line in lines:
        json.loads(line)

