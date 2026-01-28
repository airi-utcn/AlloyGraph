#!/usr/bin/env python3
"""
Convert matweb_unique_standardized.jsonl to CSV format.

The JSONL format has nested structures (composition dict, property arrays),
which need to be flattened for CSV format.
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Any


def flatten_composition(composition: Dict[str, float]) -> Dict[str, float]:
    """
    Flatten composition dictionary to comp_Element format.

    Input: {"Ni": 58.0, "Cr": 19.5, ...}
    Output: {"comp_Ni": 58.0, "comp_Cr": 19.5, ...}
    """
    return {f"comp_{element}": value for element, value in composition.items()}


def flatten_property_array(prop_name: str, prop_array: List[Dict]) -> Dict[str, Any]:
    """
    Flatten property arrays to multiple columns.

    Input: "yield_strength", [{"temp_c": "20", "value": 303.0}, {"temp_c": "650", "value": 250.0}]
    Output: {
        "yield_strength_count": 2,
        "yield_strength_temps": "20;650",
        "yield_strength_values": "303.0;250.0",
        "yield_strength_avg": 276.5,
        "yield_strength_min": 250.0,
        "yield_strength_max": 303.0,
        "yield_strength_RT": 303.0  # Room temperature value if exists
    }
    """
    if not prop_array:
        return {
            f"{prop_name}_count": 0,
            f"{prop_name}_temps": "",
            f"{prop_name}_values": "",
            f"{prop_name}_avg": None,
            f"{prop_name}_min": None,
            f"{prop_name}_max": None,
            f"{prop_name}_RT": None
        }

    temps = [str(item.get("temp_c", "")) for item in prop_array]
    values = [item.get("value", 0.0) for item in prop_array]

    # Find room temperature value (temp_c == "20" or "21")
    rt_value = None
    for item in prop_array:
        temp = str(item.get("temp_c", ""))
        if temp in ["20", "21", "25"]:  # Common RT values
            rt_value = item.get("value")
            break

    # Calculate statistics
    valid_values = [v for v in values if v is not None]

    return {
        f"{prop_name}_count": len(prop_array),
        f"{prop_name}_temps": ";".join(temps),
        f"{prop_name}_values": ";".join(map(str, values)),
        f"{prop_name}_avg": sum(valid_values) / len(valid_values) if valid_values else None,
        f"{prop_name}_min": min(valid_values) if valid_values else None,
        f"{prop_name}_max": max(valid_values) if valid_values else None,
        f"{prop_name}_RT": rt_value
    }


def flatten_record(record: Dict) -> Dict[str, Any]:
    """
    Flatten a single JSONL record to a flat dictionary for CSV.

    Input: {
        "alloy": "Alloy 625",
        "processing": "wrought",
        "form": null,
        "composition": {"Ni": 58.0, "Cr": 19.5, ...},
        "yield_strength": [{"temp_c": "20", "value": 303.0}],
        ...
    }
    Output: Flat dictionary with all fields as columns
    """
    flat = {
        "alloy": record.get("alloy", ""),
        "processing": record.get("processing", ""),
        "form": record.get("form", "")
    }

    # Keep composition as JSON string

    # Flatten composition
    flat["composition"] = json.dumps(composition) if composition else ""
    flat.update(flatten_composition(composition))

    # Count total elements

    # Keep properties as JSON strings

    # Flatten properties
    for prop in properties:
        prop_array = record.get(prop, [])
        flat[prop] = json.dumps(prop_array) if prop_array else "[]"

    return flat


        flat.update(flatten_property_array(prop, prop_array))

    """
    Convert JSONL file to CSV.

    Args:
        input_path: Path to input JSONL file
        output_path: Path to output CSV file
        include_all_temps: If True, include full temp/value arrays; if False, only include summary stats
    """
    print(f"Converting {input_path.name} to CSV...")
    print(f"Reading records...")

    # Read all records
    records = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
                flat_record = flatten_record(record)
                records.append(flat_record)
            except Exception as e:
                print(f"  Warning: Error processing line {line_num}: {e}")
                continue

    print(f"  Loaded {len(records)} records")

    if not records:
        print("❌ No records to convert!")
        return

    # Define fixed column order

        "alloy",
        "processing",
        "form",
        "total_elements",

    # Get all unique column names (some alloys may have different elements)
    all_columns = set()
    for record in records:
        all_columns.update(record.keys())

    # Sort columns for better readability
    column_order = ["alloy", "processing", "form", "total_elements"]

    # Add composition columns (comp_*)

    column_order.extend(comp_columns)

    # Add property columns
    prop_prefixes = ["yield_strength", "uts", "elongation", "elasticity"]
    for prefix in prop_prefixes:

        column_order.extend(prop_columns)

    # Add any remaining columns
    remaining = sorted(all_columns - set(column_order))
    column_order.extend(remaining)

        writer = csv.DictWriter(f, fieldnames=column_order, extrasaction='ignore')
        writer.writeheader()


    print(f"\n✅ Successfully converted {len(records)} records!")
    print(f"   Output: {output_path}")
    print(f"   Composition: {len(comp_columns)} columns")
    print(f"   Properties: {len(column_order) - 4 - len(comp_columns)} columns")

    print(f"\n📄 Sample column names:")
    print(f"   {column_order[:10]}...")
    print(f"   Composition: 1 column (JSON string)")
    print(f"   Properties: 4 columns (JSON arrays)")

    # Show sample
    print(f"\n📄 Column names:")
    print(f"   {column_order}")


def main():
    input_path = Path("/Users/lezanhawizy/github/AlloyMind/matweb_unique_standardized.jsonl")
    output_path = Path("/Users/lezanhawizy/github/AlloyMind/matweb_unique_standardized.csv")

    if not input_path.exists():
        print(f"❌ Error: Input file not found: {input_path}")
        return

    jsonl_to_csv(input_path, output_path)

    print("\n" + "="*80)
    print("CONVERSION COMPLETE!")
    print("="*80)
    print(f"\nYou can now:")
    print("\nNote: Property arrays are stored as semicolon-separated values")
    print("      (e.g., temps: '20;650;870', values: '303.0;250.0;200.0')")
    print("\nNote: Composition and properties are stored as JSON strings")
    print("      Use json.loads() to parse them back to dicts/lists")
    print("      Example: json.loads(df['composition'].iloc[0])")
    print("="*80)


if __name__ == "__main__":
    main()
