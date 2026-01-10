# AlloyMind Property Prediction Models

This directory contains the machine learning core of AlloyMind, responsible for predicting the mechanical properties of Ni-based superalloys across a wide temperature range.

## Overview
The system employs a **Hybrid Physics-ML Engine**. Instead of training on raw composition alone, we first derive meaningful metallurgical parameters to guide the models.

We train **4 ensemble models** (Random Forest + XGBoost) to predict:
1. **Yield Strength (YS)** - MPa
2. **Ultimate Tensile Strength (UTS)** - MPa  
3. **Elongation (EL)** - %
4. **Elastic Modulus (EM)** - GPa

Each model is trained using **GroupKFold cross-validation** (grouped by alloy name) to prevent data leakage.

## Core Components

### 1. Feature Engineering (`feature_engineering.py`)
This is the "Metallurgical Bridge" that transforms raw input into physical descriptors:
- **Phase Stability**: Calculates average Md (d-electron parameter) to estimate TCP phase risk.
- **Microstructure**: Estimates Gamma Prime ($\gamma'$) volume fraction based on Al, Ti, Nb, and Ta content.
- **Physical Properties**: Calculates theoretical density using the rule of mixtures.
- **Compositional Ratios**: Derives critical ratios (e.g., Al/Ti, Cr/Co) that influence oxidation resistance and strengthening.

### 2. Training Pipeline (`train_ml_models.py`)
Responsible for building and updated the models:
- **Data Source**: Consumes `final_alloy_data_enriched.jsonl`.
- **Architecture**: A **Voting Ensemble** combining **XGBoost** and **Random Forest Regressors**.
- **Cross-Validation**: Uses `GroupKFold` (grouped by Alloy name) to ensure the models generalize to unseen alloys, not just unseen temperature points for known alloys.

### 3. Inference Engine (`predictor.py`)
Provides a clean API for the rest of the application:
- **Singleton Pattern**: Ensures models are loaded into memory once.
- **Input**: Accepts a dictionary of weight percentages (wt%).
- **Execution**:
    1. Derives physical features.
    2. Expands the input across target temperatures (default 20°C to 1100°C).
    3. Returns a structured DataFrame of predictions (YS, UTS, EL, EM).

## Model Storage
- [**saved_models/**](file:///Users/alexlecu/PycharmProjects/AlloyMind/backend/alloy_crew/models/saved_models/): Contains the serialized `.pkg` files. These files bundle the trained ensemble along with the feature names required for alignment.

## Accuracy (Current Benchmarks)
| Metric | Avg R² (5-Fold CV) | Avg MAE |
| :--- | :--- | :--- |
| Yield Strength | 0.743 | 108 MPa |
| Tensile Strength | 0.712 | 132 MPa |
| Elongation | 0.418 | 10.2% |
| Elastic Modulus | 0.498 | 16.5 GPa |
