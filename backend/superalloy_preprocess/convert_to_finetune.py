import json
import random
import os
import re


def convert_to_gpt(input_file: str, output_file: str) -> None:
    """
    Converts a JSONL file of alloy data (output_data/all_alloys.jsonl) to OpenAI fine-tuning format.
    """
    converted_count = 0
    INSTRUCTION = "Predict mechanical properties based off chemical compositions and processing style"

    with open(output_file, "w", encoding="utf-8") as out_f, open(input_file, "r", encoding="utf-8") as in_f:
        for row in map(json.loads, in_f):
            # Compose user input string from available fields
            user_input = f"Alloy: {row.get('alloy', '')}; Processing: {row.get('processing', '')}; Composition: {row.get('composition', '')}"

            # Collect mechanical properties from the row (if present)
            output = {}
            for key in ["yield_strength", "uts", "elongation", "elasticity"]:
                if key in row:
                    output[key] = row[key]

            converted_count += 1
            formatted = {
                "messages": [
                    {"role": "system", "content": INSTRUCTION},
                    {"role": "user", "content": user_input}
                ]
            }
            if output:
                formatted["messages"].append(
                    {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
                )
            out_f.write(json.dumps(formatted, ensure_ascii=False) + "\n")

    print(f"Converted {converted_count} unique rows to '{output_file}'")


def split_jsonl(full_path: str, train_path: str, val_path: str, test_path: str, val_ratio: float = 0.1, test_ratio: float = 0.2, seed: int = 42) -> None:
    """
    Splits a JSONL file into train/val/test sets.
    """
    with open(full_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    random.seed(seed)
    random.shuffle(lines)

    n = len(lines)
    n_test = int(n * test_ratio)
    n_val = int(n * val_ratio)
    n_train = n - n_test - n_val
    train_lines = lines[:n_train]
    val_lines = lines[n_train:n_train + n_val]
    test_lines = lines[n_train + n_val:]

    with open(train_path, 'w', encoding='utf-8') as f:
        f.writelines(train_lines)
    with open(val_path, 'w', encoding='utf-8') as f:
        f.writelines(val_lines)
    with open(test_path, 'w', encoding='utf-8') as f:
        f.writelines(test_lines)

    print(f"Split into {len(train_lines)} train, {len(val_lines)} val, {len(test_lines)} test examples.")

# --------------------------------------------------------
# Main Execution
# --------------------------------------------------------
if __name__ == "__main__":
    # Use the all_alloys.jsonl as input, and output to finetuned_data
    input_path = os.path.join(os.path.dirname(__file__), "output_data", "all_alloys.jsonl")
    out_dir = os.path.join(os.path.dirname(__file__), "output_data", "finetuned_data")
    os.makedirs(out_dir, exist_ok=True)

    # Output file paths
    full_path = os.path.join(out_dir, "finetuned.jsonl")
    train_path = os.path.join(out_dir, "train.jsonl")
    val_path = os.path.join(out_dir, "val.jsonl")
    test_path = os.path.join(out_dir, "test.jsonl")

    convert_to_gpt(input_path, full_path)

    print(f"Written to {full_path}")
    split_jsonl(full_path, train_path, val_path, test_path)
    print(f"Train: {train_path}\nVal: {val_path}\nTest: {test_path}")
