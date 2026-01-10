from ..tools.ml_tools import AlloyPredictorTool

def test_tool():
    print("----------------------------------------------------------------")
    print("VERIFICATION STEP 1: Testing AlloyPredictorTool")
    print("----------------------------------------------------------------")

    # 1. Instantiate
    print("1. Instantiating Tool...")
    tool = AlloyPredictorTool()
    print(f"   Name: {tool.name}")
    print(f"   Desc: {tool.description[:50]}...")

    # 2. Define Test Data (Rene 125 equivalent)
    test_comp = {
        'Ni': 61.0, 'Cr': 10.0, 'Co': 10.0, 'Mo': 2.5, 'W': 7.0,
        'Ta': 3.8, 'Al': 4.8, 'Ti': 2.5, 'Hf': 1.5
    }

    temp = 20

    # 3. Run Tool
    print(f"\n2. Running Prediction for pseudo-Rene 125 at {temp}°C...")
    try:
        result = tool._run(composition=test_comp, temperature_c=temp)
        print("\n--- TOOL OUTPUT START ---")
        print(result)
        print("--- TOOL OUTPUT END ---")
        
        if "Yield Strength" in result:
            print("\n✅ SUCCESS: Tool returned valid prediction string.")
        else:
            print("\n❌ FAILED: Output format incorrect.")
            
    except Exception as e:
        print(f"\n❌ CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_tool()
