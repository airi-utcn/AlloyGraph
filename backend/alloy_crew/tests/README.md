# AlloyMind Verification Tests

This directory contains a suite of incremental tests designed to verify the core components of the AlloyMind system, from low-level ML models to complex agentic loops.

## How to Run
All tests should be executed from the `backend/` directory using the `python -m` module syntax. This ensures that the package structure is correctly resolved.

```bash
# Example: Run Step 1 (ML Tool)
cd backend
source .venv/bin/activate
python -m alloy_crew.tests.test_step_1_ml_tool
```

## Test Suite Overview

### 🧪 Step 1: ML Tool (`test_step_1_ml_tool.py`)
Tests the `AlloyPredictorTool` wrapper for CrewAI. It validates the tool signature, the integration with the physics engine (Density/Gamma Prime), and the JSON output format.

### 🧪 Step 2: RAG Tool (`test_step_2_rag_tool.py`)
Verifies the `AlloySearchTool` integration with Weaviate. Tests connectivity, property retrieval, and the multi-step GraphQL fetch logic.
