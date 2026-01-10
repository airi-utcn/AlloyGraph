import os
import json
import pytest
from backend.superalloy_preprocess import convert_to_finetune, extract_excel_sheets

@pytest.fixture(scope="module")
def output_path():
    return extract_excel_sheets.OUTPUT_PATH

@pytest.fixture(scope="module")
def finetuned_dir():
    out_dir = os.path.join(os.path.dirname(__file__), "../output_data/finetuned_data")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

@pytest.fixture(scope="module")
def finetuned_paths(finetuned_dir):
    return {
        "full": os.path.join(finetuned_dir, "finetuned.jsonl"),
        "train": os.path.join(finetuned_dir, "train.jsonl"),
        "val": os.path.join(finetuned_dir, "val.jsonl"),
        "test": os.path.join(finetuned_dir, "test.jsonl"),
    }

def test_convert_and_split(output_path, finetuned_paths):
    convert_to_finetune.convert_to_gpt(output_path, finetuned_paths["full"])
    assert os.path.exists(finetuned_paths["full"])
    convert_to_finetune.split_jsonl(
        finetuned_paths["full"],
        finetuned_paths["train"],
        finetuned_paths["val"],
        finetuned_paths["test"]
    )
    for p in finetuned_paths.values():
        assert os.path.exists(p)
        with open(p, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines:
            json.loads(line)

