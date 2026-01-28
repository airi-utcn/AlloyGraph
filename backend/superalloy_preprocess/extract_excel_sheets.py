import pandas as pd
import re
import json
import sys
import ast
from pathlib import Path

# Default paths
EXCEL_PATH = "backend/superalloy_preprocess/annotated_data/CAST_Wrought_Alloys.xlsx"
OUTPUT_PATH = "backend/superalloy_preprocess/output_data/all_alloys.jsonl"

# Matweb paths
MATWEB_EXCEL_PATH = "backend/superalloy_preprocess/evaluation_data/matweb_unique_standardized.xlsx"
MATWEB_OUTPUT_PATH = "backend/superalloy_preprocess/output_data/matweb_alloys.jsonl"
MATWEB_ORIGINAL_OUTPUT_PATH = "backend/superalloy_preprocess/output_data/matweb_original_alloys.jsonl"


def parse_numeric(val):
    """Extract numeric value from strings like '0.1Hf', '2.5', '0.03C'."""
    if isinstance(val, (int, float)):
        return float(val)

    if isinstance(val, str):
        match = re.search(r"[-+]?\d*\.?\d+", val)
        if match:
            return float(match.group())

    return None


def melt_temperature_row(row):
    out = []
    for col, val in row.items():
        if col.lower() in {"form", "alloy"}:
            continue
        if pd.notna(val) and val != "-":
            num = parse_numeric(val)
            if num is not None:
                out.append({
                    "temp_c": col.replace("C", ""),
                    "value": num
                })
    return out


def extract_all_alloys_to_jsonl():
    xls = pd.ExcelFile(EXCEL_PATH)

    # ---- Load all sheets ----
    sheets = {
        name: pd.read_excel(xls, sheet_name=name)
        for name in xls.sheet_names
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for form in ["Cast", "Wrought"]:
            alloy_sheet = f"{form} Alloy"
            if alloy_sheet not in sheets:
                continue

            alloy_df = sheets[alloy_sheet]

            for i, (idx, alloy_row) in enumerate(alloy_df.iterrows()):
                form_val = None
                ys_sheet_name = f"{form} Yield Strength"
                if ys_sheet_name in sheets:
                    ys_df = sheets[ys_sheet_name]
                    if i < len(ys_df):
                        val = ys_df.iloc[i].get("Form")
                        if pd.notna(val) and val != "-":
                            form_val = val

                result = {
                    "alloy": alloy_row.get("Alloy"),
                    "processing": form.lower(),
                    "form": form_val
                }

                # ---- Composition ----
                composition = {}
                for k, v in alloy_row.items():
                    if k == "Alloy" or pd.isna(v) or v == "-":
                        continue

                    num = parse_numeric(v)
                    if num is not None:
                        composition[k] = num

                result["composition"] = composition

                # ---- Properties ----
                for prop in ["Yield Strength", "UTS", "Elongation", "Elasticity"]:
                    sheet_name = f"{form} {prop}"
                    if sheet_name in sheets and idx < len(sheets[sheet_name]):
                        prop_row = sheets[sheet_name].iloc[idx]
                        result[prop.replace(" ", "_").lower()] = melt_temperature_row(prop_row)

                f.write(json.dumps(result, ensure_ascii=False) + "\n")


def extract_matweb_alloys_to_jsonl():
    """Extract alloys from matweb_unique_standardized.xlsx to JSONL format."""
    xls = pd.ExcelFile(MATWEB_EXCEL_PATH)

    # Load the main sheet
    df = pd.read_excel(xls, sheet_name='matweb_unique_standardized')

    with open(MATWEB_OUTPUT_PATH, "w", encoding="utf-8") as f:
        for idx, row in df.iterrows():
            result = {
                "alloy": row.get("alloy"),
                "processing": row.get("form"),  # "wrought" or "cast"
                "form": row.get("form")  # Keep consistent with original format
            }

            # Parse composition from JSON string
            composition_str = row.get("composition")
            if pd.notna(composition_str) and composition_str != "-":
                try:
                    result["composition"] = json.loads(composition_str)
                except (json.JSONDecodeError, TypeError):
                    result["composition"] = {}
            else:
                result["composition"] = {}

            # Parse properties from JSON strings
            for prop_col, prop_key in [
                ("yield_strength", "yield_strength"),
                ("uts", "uts"),
                ("elongation", "elongation"),
                ("elasticity", "elasticity")
            ]:
                prop_str = row.get(prop_col)
                if pd.notna(prop_str) and prop_str != "-":
                    try:
                        result[prop_key] = json.loads(prop_str)
                    except (json.JSONDecodeError, TypeError):
                        result[prop_key] = []
                else:
                    result[prop_key] = []

            f.write(json.dumps(result, ensure_ascii=False) + "\n")


def extract_matweb_original_to_jsonl():
    """Extract alloys from 'Original MATWEB sheet' and convert properties to standard format."""
    xls = pd.ExcelFile(MATWEB_EXCEL_PATH)

    # Load the Original MATWEB sheet
    df = pd.read_excel(xls, sheet_name='Original MATWEB sheet')

    with open(MATWEB_ORIGINAL_OUTPUT_PATH, "w", encoding="utf-8") as f:
        for idx, row in df.iterrows():
            result = {
                "alloy": row.get("alloy"),  # Fixed: was "alloy_name"
                "processing": row.get("form"),
                "form": row.get("form")
            }

            # Parse composition (can be a dict, Python dict string, or JSON string)
            composition = row.get("composition")
            if pd.notna(composition) and composition != "-":
                if isinstance(composition, str):
                    try:
                        # Try parsing as Python literal (handles single quotes)
                        result["composition"] = ast.literal_eval(composition)
                    except (ValueError, SyntaxError):
                        try:
                            # Fall back to JSON parsing
                            result["composition"] = json.loads(composition)
                        except (json.JSONDecodeError, TypeError):
                            result["composition"] = {}
                elif isinstance(composition, dict):
                    result["composition"] = composition
                else:
                    result["composition"] = {}
            else:
                result["composition"] = {}

            # Convert tensile_strength_mpa to uts with temp_c format
            tensile_strength = row.get("tensile_strength_mpa")
            if pd.notna(tensile_strength) and tensile_strength != "-":
                try:
                    result["uts"] = [{"temp_c": "20", "value": float(tensile_strength)}]
                except (ValueError, TypeError):
                    result["uts"] = []
            else:
                result["uts"] = []

            # Convert yield_strength_mpa to yield_strength with temp_c format
            yield_strength = row.get("yield_strength_mpa")
            if pd.notna(yield_strength) and yield_strength != "-":
                try:
                    result["yield_strength"] = [{"temp_c": "20", "value": float(yield_strength)}]
                except (ValueError, TypeError):
                    result["yield_strength"] = []
            else:
                result["yield_strength"] = []

            # Convert elongation_pct to elongation with temp_c format
            elongation = row.get("elongation_pct")
            if pd.notna(elongation) and elongation != "-":
                try:
                    result["elongation"] = [{"temp_c": "20", "value": float(elongation)}]
                except (ValueError, TypeError):
                    result["elongation"] = []
            else:
                result["elongation"] = []

            # Handle elasticity if present
            elasticity = row.get("elasticity")
            if pd.notna(elasticity) and elasticity != "-":
                try:
                    result["elasticity"] = [{"temp_c": "20", "value": float(elasticity)}]
                except (ValueError, TypeError):
                    result["elasticity"] = []
            else:
                result["elasticity"] = []

            f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "matweb":
        print(f"Extracting matweb alloys from {MATWEB_EXCEL_PATH}...")
        extract_matweb_alloys_to_jsonl()
        print(f"Done! Output written to {MATWEB_OUTPUT_PATH}")
    elif len(sys.argv) > 1 and sys.argv[1] == "matweb-original":
        print(f"Extracting Original MATWEB sheet from {MATWEB_EXCEL_PATH}...")
        extract_matweb_original_to_jsonl()
        print(f"Done! Output written to {MATWEB_ORIGINAL_OUTPUT_PATH}")
    elif len(sys.argv) > 1 and sys.argv[1] == "matweb-both":
        print(f"Extracting both matweb sheets from {MATWEB_EXCEL_PATH}...")
        extract_matweb_alloys_to_jsonl()
        print(f"  - Standardized sheet written to {MATWEB_OUTPUT_PATH}")
        extract_matweb_original_to_jsonl()
        print(f"  - Original sheet written to {MATWEB_ORIGINAL_OUTPUT_PATH}")
        print("Done!")
    else:
        print(f"Extracting alloys from {EXCEL_PATH}...")
        extract_all_alloys_to_jsonl()
        print(f"Done! Output written to {OUTPUT_PATH}")

