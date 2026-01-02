"""Test: Good alloy evaluation - Happy path."""
import json
from ..alloy_evaluator import AlloyEvaluationCrew


if __name__ == "__main__":
    print("\n🧪 TEST: Good Alloy Property Prediction\n")
    
    evaluator = AlloyEvaluationCrew()
    
    # Test composition - cast Ni-based superalloy
    test_composition = {
        "Ni": 55.0, "Cr": 20.0, "Co": 20.0, "Mo": 5.8, 
        "Al": 0.5, "Ti": 2.2, "Fe": 0.5, "Mn": 0.5, 
        "C": 0.06, "B": 0.008, "Zr": 0.04
    }
    
    result = evaluator.run(
        composition=test_composition, 
        processing="cast",
        temperature=20
    )
    
    print("\n✅ RESULT:")
    print(json.dumps(result, indent=2))
    
    # Assertions
    assert result.get("status") == "PASS", f"Expected PASS, got {result.get('status')}"
    
    props = result.get("properties", {})
    assert "Yield Strength" in props, "Missing Yield Strength"
    assert "Tensile Strength" in props, "Missing Tensile Strength"
    assert "Elongation" in props, "Missing Elongation"
    
    # Display confidence summary
    confidence = result.get("confidence", {})
    score = confidence.get('score', 0)
    print("\n" + "="*60)
    print(f"CONFIDENCE: {score:.3f} ({confidence.get('level', 'N/A')})")
    print(f"KG Match: {confidence.get('matched_alloy', 'None')}")
    print("="*60)
    print("✅ TEST PASSED!")
    print("="*60)
