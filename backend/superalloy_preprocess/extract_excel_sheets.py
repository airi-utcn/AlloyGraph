import pandas as pd
import re
import json

EXCEL_PATH = "backend/superalloy_preprocess/annotated_data/CAST_Wrought_Alloys.xlsx"
OUTPUT_PATH = "backend/superalloy_preprocess/output_data/all_alloys.jsonl"


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


extract_all_alloys_to_jsonl()