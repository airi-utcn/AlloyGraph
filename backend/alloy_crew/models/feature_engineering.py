from typing import Dict, Any

# Physical constants
ATOMIC_WEIGHTS = {
    "Ni": 58.69, "Co": 58.93, "Cr": 52.00, "Mo": 95.95, "W": 183.84,
    "Al": 26.98, "Ti": 47.87, "Ta": 180.95, "Nb": 92.91, "Re": 186.21,
    "Fe": 55.85, "C": 12.01, "B": 10.81, "Hf": 178.49, "Zr": 91.22,
    "Ru": 101.07, "V": 50.94, "Mn": 54.94, "Si": 28.09, "Cu": 63.55,
    "N": 14.01, "La": 138.91, "Y": 88.91
}

# Morinaga d-electron parameter values (Md)
MD_VALUES = {
    "Ni": 0.717, "Co": 0.777, "Cr": 1.142, "Mo": 1.55, "W": 1.655,
    "Al": 1.9, "Ti": 2.271, "Ta": 2.224, "Nb": 2.117, "Re": 1.267,
    "Fe": 0.858, "Hf": 3.0, "Zr": 2.9, "Ru": 1.006, "V": 1.543
}

# Element densities (g/cm³)
ELEMENT_DENSITIES = {
    "Ni": 8.90, "Co": 8.90, "Cr": 7.19, "Mo": 10.28, "W": 19.25,
    "Al": 2.70, "Ti": 4.50, "Ta": 16.69, "Nb": 8.57, "Re": 21.02,
    "Fe": 7.87, "Hf": 13.31, "Zr": 6.51, "Ru": 12.37, "V": 6.11,
    "Mn": 7.21, "Si": 2.33, "Cu": 8.96, "C": 2.26, "B": 2.34
}


def wt_to_at_percent(composition: Dict[str, float]) -> Dict[str, float]:
    """Convert weight percent to atomic percent."""
    moles: Dict[str, float] = {}
    for el, wt in composition.items():
        if el in ATOMIC_WEIGHTS and wt > 0:
            moles[el] = wt / ATOMIC_WEIGHTS[el]
    
    # Calculate total moles
    total_moles = sum(moles.values())
    if total_moles == 0:
        return {el: 0.0 for el in ATOMIC_WEIGHTS}
    
    # Calculate atomic percent
    at_pct = {el: round(m / total_moles * 100, 2) for el, m in moles.items()}
    
    return at_pct


def calculate_md_avg(at_percent: Dict[str, float]) -> float:
    """Calculate average Md (Morinaga d-electron) parameter."""
    md_sum = 0.0
    total = 0.0
    
    for el, at_pct in at_percent.items():
        if el in MD_VALUES:
            md_sum += (at_pct / 100) * MD_VALUES[el]
            total += at_pct / 100
    
    return round(md_sum, 4) if total > 0 else 0.0


def calculate_density(composition: Dict[str, float]) -> float:
    """Calculate alloy density using rule of mixtures."""
    total_wt = sum(composition.values())
    if total_wt == 0:
        return 8.0  # Default Ni-base density
    
    # Simple rule of mixtures for estimate
    density = sum(
        (wt / total_wt) * ELEMENT_DENSITIES.get(el, 8.0)
        for el, wt in composition.items()
    )
    return round(density, 3)


def estimate_gamma_prime_vol_pct(at_percent: Dict[str, float]) -> float:
    """Estimate gamma prime volume fraction from composition."""
    gp_formers = (
        at_percent.get("Al", 0) +
        at_percent.get("Ti", 0) +
        0.6 * at_percent.get("Nb", 0) +
        0.5 * at_percent.get("Ta", 0)
    )
    return round(min(2.5 * gp_formers, 80), 1)


def compute_alloy_features(alloy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point to compute all features for an alloy.
    """
    raw_comp = alloy.get("composition", {})
    # Sanitize: Keep only numeric values (ignore 'other', 'balance', strings)
    composition = {k: v for k, v in raw_comp.items() if isinstance(v, (int, float))}

    at_percent = wt_to_at_percent(composition)
    md_avg = calculate_md_avg(at_percent)
    
    # 2. Build feature dictionary
    features = {
        # === Atomic Percentages ===
        "atomic_percent": at_percent,
        
        # === Morinaga Parameter ===
        "Md_avg": md_avg,
        "TCP_risk": "high" if md_avg > 0.985 else "low",
        
        # === Density ===
        "density_calculated_gcm3": calculate_density(composition),
        
        # === Gamma Prime Estimate ===
        "gamma_prime_estimated_vol_pct": estimate_gamma_prime_vol_pct(at_percent),
        
        # === Solid Solution Strengtheners (wt%) ===
        "SSS_total_wt_pct": round(sum(composition.get(el, 0) for el in ["Mo", "W", "Nb", "Ta", "Re"]), 2),
        
        # === Refractory Elements (wt%) ===
        "refractory_total_wt_pct": round(sum(composition.get(el, 0) for el in ["Mo", "W", "Ta", "Re", "Nb", "Hf"]), 2),
        
        # === Gamma Prime Formers (wt%) ===
        "GP_formers_wt_pct": round(sum(composition.get(el, 0) for el in ["Al", "Ti", "Ta", "Nb"]), 2),
        
        # === Key Element Ratios ===
        "Al_Ti_ratio": round(composition.get("Al", 0) / (composition.get("Ti", 0) + 0.01), 2),
        "Cr_Co_ratio": round(composition.get("Cr", 0) / (composition.get("Co", 0) + 0.01), 2),
        "Cr_Ni_ratio": round(composition.get("Cr", 0) / (composition.get("Ni", 0) + 0.01), 3),
        "Mo_W_ratio": round(composition.get("Mo", 0) / (composition.get("W", 0) + 0.01), 2),
        
        # === Atomic Percent Ratios ===
        "Al_Ti_at_ratio": round(at_percent.get("Al", 0) / (at_percent.get("Ti", 0) + 0.01), 2),
        
        # === Total GP Formers (at%) ===
        "GP_formers_at_pct": round(sum(at_percent.get(el, 0) for el in ["Al", "Ti", "Ta", "Nb"]), 2),
    }
    
    return features
