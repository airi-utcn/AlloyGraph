from ..tools.rag_tools import AlloySearchTool

def test_rag_tool():
    print("----------------------------------------------------------------")
    print("VERIFICATION STEP 2: Testing AlloyKnowledgeGraphSearch Tool")
    print("----------------------------------------------------------------")

    # 1. Instantiate
    print("1. Instantiating Tool...")
    tool = AlloySearchTool()
    print(f"   Name: {tool.name}")

    # 2. Define Test Data (Known Alloy: UDIMET 500)
    test_comp = {"Ni": 52.0, "Cr": 18.0, "Co": 19.0, "Mo": 4.2, "Al": 3.0, "Ti": 3.0, "C": 0.07, "B": 0.007, "Zr": 0.05}
    
    # 3. Run Tool
    print(f"\n2. Searching for similar alloys (Input: Ni-19Cr-19Fe-5Nb)...")
    try:
        # We limit to 3 results for brevity
        result = tool._run(composition=test_comp, limit=3)
        
        print("\n--- TOOL OUTPUT START ---")
        print(result)
        print("--- TOOL OUTPUT END ---")
        
        if "Error" in result:
            print("\n❌ FAILED: Weaviate connection error.")
        elif "No similar alloys" in result:
            print("\n⚠️ WARNING: Connected, but found no alloys. Is Database populated?")
        else:
            print("\n✅ SUCCESS: Tool returned data from Knowledge Graph.")
            
    except Exception as e:
        print(f"\n❌ CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_rag_tool()
