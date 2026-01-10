import pandas as pd
import json
import math
import ast

# Input and output paths
csv_path = "backend/superalloy_preprocess/input_data/annotated_superalloys.csv"
jsonl_path = "backend/superalloy_preprocess/output_data/alloydata_20251205_filtered.jsonl"

# Read the CSV
df = pd.read_csv(csv_path, dtype=str)

# Mechanical property columns to nest
mech_cols = [
    'mechanical_properties_tensile_strength_mpa',
    'mechanical_properties_yield_strength_mpa',
    'mechanical_properties_elongation_pct',
    'mechanical_properties_hardness',
    'mechanical_properties_creep_rupture_hours',
    'mechanical_properties_reduction_of_area_pct',
    # Add these columns to always include them
    'tensile_strength_mpa',
    'yield_strength_mpa',
    'elongation_pct'
]

# Top-level columns
top_level = [
    'alloy','uns','family','density_gcm3','gamma_prime_vol_pct','typical_heat_treatment',
    'composition','density'
]

# Variant columns
variant_cols = ['variant_name', 'processing', 'source']

def nan_to_none(val):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, str) and val.lower() in ['nan', 'none', '']:
        return None
    return val

def parse_mech_value(val, key=None):
    if key in ['tensile_strength_mpa', 'yield_strength_mpa', 'elongation_pct']:
        return [{"temp_c": 20, "value": val}]
    val = nan_to_none(val)
    if val is None:
        return None
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        # Try JSON or Python list/dict
        try:
            parsed = json.loads(val)
            return parsed
        except Exception:
            try:
                parsed = ast.literal_eval(val)
                # print(parsed)
                return parsed
            except Exception:
                # If it's a number in string form, wrap in list of dicts
                try:
                    num = float(val)
                    # For the three key columns, wrap with temp_c=20
                    print(key)
                    return [{"temp_c": 20, "value": num}]
                    # if key in ['tensile_strength_mpa', 'yield_strength_mpa', 'elongation_pct']:
                    #     return [{"temp_c": 20, "value": num}]
                    # else:
                    #     print("here")
                    #     return [{"value": num}]
                except Exception:
                    return None
    # If it's a number, wrap in list of dicts
    if isinstance(val, (int, float)):
        if key in ['tensile_strength_mpa', 'yield_strength_mpa', 'elongation_pct']:
            print(key,val)
            return [{"temp_c": 20, "value": val}]
        else:
            print("val", val)
            return [{"value": val}]
    return None

with open(jsonl_path, 'w', encoding='utf-8') as outfile:
    for _, row in df.iterrows():
        # Build top-level dict
        obj = {col: nan_to_none(row.get(col)) for col in top_level}
        # Build variant
        variant = {col: nan_to_none(row.get(col)) for col in variant_cols}
        # Build mechanical_properties dict
        mech = {}
        for col in mech_cols:
            key = col.replace('mechanical_properties_', '')

            mech[key] = parse_mech_value(row.get(col), key)
        variant['mechanical_properties'] = mech
        # Only one variant per row
        obj['variants'] = [variant]
        # Write as JSONL
        outfile.write(json.dumps(obj, ensure_ascii=False) + '\n')
