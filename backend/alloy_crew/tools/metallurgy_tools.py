from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Dict, Any, Literal
import json

from ..models.feature_engineering import compute_alloy_features

def validate_property_bounds(properties: Dict[str, Any]) -> list[str]:
    """
    Validates that predicted properties are within physically reasonable bounds.
    Returns a list of error messages for properties that violate physical constraints.
    """
    errors = []
    
    ys = properties.get('Yield Strength', 0)
    uts = properties.get('Tensile Strength', 0)
    el = properties.get('Elongation', 0)
    density = properties.get('Density', 0)
    gp = properties.get('Gamma Prime', 0)
    em = properties.get('Elastic Modulus', 0)
    
    # Physical impossibilities
    if ys > uts and uts > 0:
        errors.append(f"Yield Strength ({ys} MPa) > UTS ({uts} MPa) - physically impossible")
    
    # Known superalloy limits (Based on literature: Reed 2006, Pollock & Tin 2006)
    if ys > 2000:
        errors.append(f"Yield Strength ({ys} MPa) exceeds known superalloy limits (~2000 MPa)")
    if uts > 2500:
        errors.append(f"Tensile Strength ({uts} MPa) exceeds known superalloy limits (~2500 MPa)")
    
    # Elongation bounds
    if el < 0:
        errors.append(f"Elongation ({el}%) cannot be negative")
    if el > 100:
        errors.append(f"Elongation ({el}%) exceeds 100% - physically impossible")
    
    # Elastic Modulus bounds for Ni-based superalloys (typically 180-220 GPa, hard limits 150-250)
    if em > 0:  # Only check if provided
        if em < 150 or em > 250:
            errors.append(f"Elastic Modulus ({em} GPa) outside physically reasonable range for Ni-superalloys (150-250 GPa)")
        elif em < 180 or em > 220:
            errors.append(f"Elastic Modulus ({em} GPa) outside typical Ni-superalloy range (180-220 GPa) - verify composition")
    
    # Density bounds for Ni-based superalloys (typically 7.5-9.5 g/cm³)
    if density > 0:  # Only check if provided
        if density < 7.0 or density > 10.0:
            errors.append(f"Density ({density} g/cm³) out of typical Ni-superalloy range (7.5-9.5)")
    
    # Gamma Prime volume fraction bounds (0-70% typical)
    if gp > 0:  # Only check if provided
        if gp > 75:
            errors.append(f"Gamma Prime ({gp}%) exceeds typical maximum (~70%)")
    
    return errors


def calculate_em_rule_of_mixtures(composition: Dict[str, float]) -> float:
    """
    Calculate Elastic Modulus using rule of mixtures.
    Based on elemental Young's moduli at room temperature.
    """
    elemental_moduli = {
        "Ni": 200.0,
        "Cr": 279.0,
        "Co": 209.0,
        "Al": 70.0,
        "Ti": 116.0,
        "Mo": 329.0,
        "W": 411.0,
        "Fe": 211.0
    }
    
    em = sum(composition.get(element, 0) / 100.0 * modulus 
             for element, modulus in elemental_moduli.items())
    
    return em


class MetallurgyVerifierInput(BaseModel):
    """Input for metallurgy verification."""
    composition: Dict[str, float] = Field(..., description="Alloy composition dict.")
    anchored_properties_json: str = Field(..., description="JSON output from the DataFusionTool containing 'anchored_properties'.")
    temperature_c: float = Field(..., description="Temperature in Celsius.")
    alloy_type: Literal['high_strength', 'high_corrosion', 'standard'] = Field('standard', description="LLM-inferred alloy class based on Cr/Ti/Al levels.")

class MetallurgyVerifierTool(BaseTool):
    name: str = "MetallurgyVerifierTool"
    description: str = (
        "Applies metallurgical laws. Requires 'alloy_type' inferred by Agent analysis of Cr/Ti/Al levels."
    )
    args_schema: Type[BaseModel] = MetallurgyVerifierInput

    def _run(self, composition: Dict[str, float], anchored_properties_json: str, temperature_c: float, alloy_type: str = 'standard', **kwargs: Any) -> str:
        try:
            clean_json = anchored_properties_json.replace("```json", "").replace("```", "").strip()
            if "{" in clean_json:
                 start = clean_json.find("{")
                 end = clean_json.rfind("}") + 1
                 clean_json = clean_json[start:end]
            input_data = json.loads(clean_json)
            props = input_data.get('anchored_properties') or input_data.get('properties') or input_data

        except:
            input_data = {}
            props = {}

        composition = {k: float(v) for k, v in composition.items()}
        features = compute_alloy_features(composition)

        gp = features["gamma_prime_estimated_vol_pct"]
        md_avg = features["Md_avg"]
        density = features["density_calculated_gcm3"]
        sss_wt = features["SSS_total_wt_pct"]

        try:
            raw_ys = float(props.get('Yield Strength', 0))
            raw_ts = float(props.get('Tensile Strength', 0))
            raw_el = float(props.get('Elongation', 0))
            raw_em = float(props.get('Elastic Modulus', 0))
            
            alloy_type = str(alloy_type).lower().strip().replace(" ", "_")
            if "corrosion" in alloy_type: 
                alloy_type = "high_corrosion"
            elif "strength" in alloy_type: 
                alloy_type = "high_strength"
            else: 
                alloy_type = "standard"

            processing = (input_data.get("processing") or input_data.get("family") or "unknown").lower()
            
            if processing == "unknown":
                if composition.get("B", 0) > 0.005 and composition.get("Zr", 0) > 0.03:
                    processing = "cast"
                else:
                    processing = "wrought"
            
            if "cast" in processing or "nimocast" in str(input_data).lower():
                processing = "cast"
            elif "wrought" in processing or "forged" in processing:
                processing = "wrought"

            if processing == "cast":
                 base_ductility = 20.0
                 hall_petch_boost = 0.0
            else:
                 base_ductility = 40.0
                 hall_petch_boost = 50.0
            
            base_ni = 120.0 + hall_petch_boost
            sss_contribution = (12.0 * sss_wt)
            BASE_STRENGTH = base_ni + sss_contribution
            
            COEFF_GP = 25.0
            if alloy_type == 'high_strength':
                COEFF_GP = 45.0
            elif alloy_type == 'high_corrosion':
                COEFF_GP = 15.0
            
            COEFF_SSS = 5.0 
            
            ys_physics = BASE_STRENGTH + (COEFF_GP * gp) + (COEFF_SSS * sss_wt)

            el_physics = base_ductility - (0.8 * gp) - (0.5 * sss_wt)
            
            if processing == "wrought":
                if el_physics < 12.0: el_physics = 12.0
            else:
                if el_physics < 5.0: el_physics = 5.0

            # Elastic Modulus - Physics-based calculation
            em_physics = calculate_em_rule_of_mixtures(composition)

            if 'metallurgy_metrics' not in input_data: input_data['metallurgy_metrics'] = {}
            input_data['metallurgy_metrics']['gamma_prime_vol'] = gp

            fusion_meta = input_data.get("fusion_meta", {})
            is_kg_anchored = fusion_meta.get("is_kg_anchored", False)
            
            confidence = input_data.get("confidence")
            if not isinstance(confidence, dict):
                # Handle simplified input from agents (float/int)
                if isinstance(confidence, (float, int)):
                     confidence = {
                        "score": float(confidence),
                        "level": "MEDIUM" if confidence > 0.6 else "LOW", 
                        "note": "Reconstructed from scalar"
                     }
                else:
                    # Default fallback
                    confidence = {
                        "score": 0.50,
                        "level": "MEDIUM",
                        "kg_weight_used": 0.0,
                        "similarity_distance": 999.0,
                        "temperature_delta": 0.0,
                        "matched_alloy": "None"
                    }

            if is_kg_anchored:
                final_ys = raw_ys
                final_el = raw_el
                final_em = raw_em
            else:
                final_ys = (raw_ys * 0.6) + (ys_physics * 0.4)
                final_el = (raw_el * 0.6) + (el_physics * 0.4)
                final_em = (raw_em * 0.6) + (em_physics * 0.4)
            
            warnings = []
            if gp < 5.0 and "solid_solution" not in processing:
                 if sss_wt < 10.0:
                     warnings.append(f"Low Gamma Prime ({gp:.1f}%) and low SSS.")
            
            if md_avg > 0.99:
                warnings.append(f"High Md ({md_avg:.3f}) phase instability risk.")

            if is_kg_anchored:
                 final_ts = raw_ts
            else:
                 strength_scale = final_ys / (raw_ys + 0.1)
                 final_ts = raw_ts * strength_scale

            # Calculate Penalty Score for Agents
            penalty_score = 0
            if warnings:
                penalty_score += len(warnings) * 10
            
            # Additional penalty for very high Md even if not warned (soft limit)
            if md_avg > 0.985:
                penalty_score += 15
                if "High Md" not in str(warnings):
                    warnings.append(f"Elevated Md ({md_avg:.3f}) - borderline risk.")
            
            # Validate property bounds
            verified_props = {
                "Yield Strength": int(final_ys),
                "Tensile Strength": int(final_ts),
                "Elongation": round(final_el, 1),
                "Elastic Modulus": round(final_em, 1),
                "Density": round(density, 2),
                "Gamma Prime": round(gp, 1)
            }
            
            bounds_errors = validate_property_bounds(verified_props)
            if bounds_errors:
                warnings.extend(bounds_errors)
                penalty_score += len(bounds_errors) * 15  # Heavy penalty for physical impossibilities

            output_data = {
                "summary": f"Physics Audit Complete. Penalty Score: {penalty_score}. {len(warnings)} Warnings Generated.",
                "processing": processing,
                "penalty_score": penalty_score, # Explicit field for Agent Logic
                "properties": verified_props,
                "property_intervals": input_data.get("property_intervals", {}),  # Pass through intervals from fusion/ML
                "metallurgy_metrics": {
                    "md_average": round(md_avg, 3),
                    "tcp_risk": "High" if md_avg > 1.02 else ("Medium" if md_avg > 0.99 else "Low"),
                    "sss_wt_pct": round(sss_wt, 2),
                    "base_contribution": int(BASE_STRENGTH)
                },
                "warnings": warnings,
                "confidence": confidence,
                "explanation": ""  # Agent will generate this
            }
            return json.dumps(output_data, indent=2)

        except Exception as e:
            return json.dumps({"status": "FAIL", "error": f"Physics Constraint Error: {str(e)}", "properties": {}})
