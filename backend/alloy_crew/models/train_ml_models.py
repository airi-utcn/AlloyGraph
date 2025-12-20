import json
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor, VotingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import joblib


def flatten_dict(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def load_data_for_target(filepath: str, target_metric: str):
    """
    Loads data specifically for a given target (YS, UTS, or EL).
    """
    rows = []
    with open(filepath, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                alloy_name = entry.get('alloy', 'Unknown')
                
                base_feats = flatten_dict(entry.get('computed_features', {}))
                
                base_feats['family'] = entry.get('family', 'unknown')
                base_feats['TCP_risk'] = base_feats.get('TCP_risk', 'unknown') 
                
                variants = entry.get('variants', [])
                for variant in variants:
                    mech = variant.get('mechanical_properties', {})
                    
                    measurements = mech.get(target_metric)
                    
                    if not measurements or not isinstance(measurements, list): continue
                        
                    for point in measurements:
                        row = base_feats.copy()
                        row['test_temperature_c'] = point.get('temp_c', 20)
                        row['target'] = point.get('value')
                        row['alloy_name'] = alloy_name
                        
                        if row['target'] is not None:
                            rows.append(row)
            except Exception: continue
    
    df = pd.DataFrame(rows)
    # Fill missing values (sparse features) with 0
    df = df.fillna(0)
    return df


def train_model(df, target_name, rf_params=None, xgb_params=None):
    print(f"\n{'='*60}")
    print(f"TRAINING: {target_name.upper()}")
    print(f"Dataset Size: {len(df)} points")
    print(f"{'='*60}")
    
    X = df.drop(columns=['target', 'alloy_name'])
    y = df['target']

    groups = df['alloy_name']
    feature_names = X.columns.tolist()

    cat_cols = [col for col in X.columns if X[col].dtype == 'object']
    num_cols = [col for col in X.columns if X[col].dtype != 'object']
    
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', 'passthrough', num_cols),
            ('cat', OneHotEncoder(handle_unknown='ignore'), cat_cols)
        ]
    )
    
    # Default Params if None
    if rf_params is None: rf_params = {'n_estimators': 200, 'random_state': 42}
    if xgb_params is None: xgb_params = {'n_estimators': 300, 'random_state': 42}
    
    rf = RandomForestRegressor(**rf_params, n_jobs=-1)
    gb = xgb.XGBRegressor(**xgb_params, n_jobs=-1)
    
    ensemble = VotingRegressor(estimators=[('rf', rf), ('xgb', gb)], n_jobs=-1)
    
    pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('model', ensemble)
    ])

    gkf = GroupKFold(n_splits=5)
    mae_scores = []
    r2_scores = []
    
    for i, (train_idx, test_idx) in enumerate(gkf.split(X, y, groups=groups)):
        pipeline.fit(X.iloc[train_idx], y.iloc[train_idx])
        preds = pipeline.predict(X.iloc[test_idx])
        
        mae = mean_absolute_error(y.iloc[test_idx], preds)
        r2 = r2_score(y.iloc[test_idx], preds)
        mae_scores.append(mae)
        r2_scores.append(r2)
        print(f"  Fold {i+1}: MAE = {mae:.1f} | R² = {r2:.3f}")

    print(f"  > Avg MAE: {np.mean(mae_scores):.2f}")
    print(f"  > Avg R² : {np.mean(r2_scores):.3f}")
    
    pipeline.fit(X, y)
    return pipeline, feature_names


if __name__ == "__main__":
    # DATA_FILE = "/Users/alexlecu/PycharmProjects/AlloyMind/backend/scrape/combined_alloys_20251206.jsonl"
    DATA_FILE = "/Users/alexlecu/PycharmProjects/AlloyMind/backend/alloy_crew/final_enriched.jsonl"

    targets = {
        "ys":  {
            "key": "yield_strength_mpa",   
            "name": "Yield Strength",
            "rf_params": {'n_estimators': 200, 'min_samples_split': 2, 'min_samples_leaf': 1, 'max_features': 'log2', 'max_depth': 20, 'random_state': 42},
            "xgb_params": {'subsample': 0.9, 'n_estimators': 500, 'max_depth': 7, 'learning_rate': 0.05, 'colsample_bytree': 0.9, 'random_state': 42}
        },
        "uts": {
            "key": "tensile_strength_mpa", 
            "name": "Tensile Strength",
            "rf_params": {'n_estimators': 500, 'min_samples_split': 2, 'min_samples_leaf': 1, 'max_features': 'sqrt', 'max_depth': 10, 'random_state': 42},
            "xgb_params": {'subsample': 0.7, 'n_estimators': 500, 'max_depth': 5, 'learning_rate': 0.01, 'colsample_bytree': 0.8, 'random_state': 42}
        },
        "el":  {
            "key": "elongation_pct",       
            "name": "Elongation",
            "rf_params": {'n_estimators': 500, 'min_samples_split': 2, 'min_samples_leaf': 1, 'max_features': 'sqrt', 'max_depth': 10, 'random_state': 42},
            "xgb_params": {'subsample': 0.8, 'n_estimators': 300, 'max_depth': 7, 'learning_rate': 0.1, 'colsample_bytree': 0.9, 'random_state': 42}
        }
    }

    for model_id, config in targets.items():
        filename = f"model_{model_id}.pkg"

        df = load_data_for_target(DATA_FILE, config["key"])
        if not df.empty:
            model, features = train_model(
                df, 
                config["name"],
                rf_params=config.get("rf_params"),
                xgb_params=config.get("xgb_params")
            )
            joblib.dump({'model': model, 'features': features}, filename)
        else:
            print(f"Warning: No data found for {config['name']}")
