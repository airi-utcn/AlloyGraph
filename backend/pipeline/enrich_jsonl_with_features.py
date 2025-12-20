import json
import sys
from typing import Dict, Any

from backend.alloy_crew.models.feature_engineering import compute_alloy_features


def compute_features(alloy: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all metallurgical features for an alloy using the shared library."""
    return compute_alloy_features(alloy)


def enrich_alloy(alloy: Dict[str, Any]) -> Dict[str, Any]:
    """Add computed features to an alloy record."""
    enriched = alloy.copy()

    computed = compute_features(alloy)
    enriched["computed_features"] = computed

    return enriched


def main():
    if len(sys.argv) != 3:
        print("Usage: python enrich_jsonl_with_features.py input.jsonl output.jsonl")
        print("\nThis script adds computed metallurgical features to each alloy record.")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]

    enriched_records = []
    error_count = 0
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                alloy = json.loads(line)
                enriched = enrich_alloy(alloy)
                enriched_records.append(enriched)
            except Exception as e:
                print(f"Error on line {i}: {e}")
                error_count += 1
    
    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        for record in enriched_records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    # Summary
    print(f"✓ Enriched {len(enriched_records)} alloys")
    print(f"✓ Output saved to: {output_file}")
    if error_count:
        print(f"⚠ {error_count} records had errors")
    
if __name__ == '__main__':
    main()
