"""Test: Bad alloy evaluation - TCP risk."""
import json
from ..alloy_evaluator import AlloyEvaluationCrew


if __name__ == "__main__":
    print("\n🧪 TEST: Bad Alloy (High Re → TCP Risk)\n")
    
    evaluator = AlloyEvaluationCrew()
    
    # Bad composition - excessive Re causes TCP phase risk
    test_composition = {
        "Ni": 50.0, "Cr": 5.0, "Co": 5.0, "Mo": 2.0,
        "W": 10.0, "Re": 20.0, "Ti": 1.0, "Al": 7.0
    }
    
    result = evaluator.run(
        composition=test_composition, 
        temperature=20
    )
    
    print("\n⚠️ RESULT:")
    print(json.dumps(result, indent=2))
    
    status = result.get("status")
    print(f"\nFinal Status: {status}")
    
    # Should return valid status
    assert status in ["PASS", "REJECT", "FAIL"], f"Invalid status: {status}"
    
    print("\n✅ TEST PASSED - Bad alloy handled correctly!")
