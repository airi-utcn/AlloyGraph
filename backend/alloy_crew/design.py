import argparse
import sys
from .alloy_designer import IterativeDesignCrew


def validate_design_inputs(ys, uts, el, density, iterations):
    """
    Validate input parameters for physical feasibility.
    
    Args:
        ys: Yield strength (MPa)
        uts: Ultimate tensile strength (MPa)
        el: Elongation (%)
        density: Density (g/cm³)
        iterations: Number of design iterations
    
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # 1. UTS must be >= YS (if both specified)
    if uts > 0 and ys > 0:
        if uts < ys:
            errors.append(f"❌ Tensile Strength ({uts} MPa) cannot be less than Yield Strength ({ys} MPa)")
    
    # 2. Yield strength range check (superalloys typically 200-2000 MPa)
    if ys > 0:
        if ys < 100:
            errors.append(f"❌ Yield Strength ({ys} MPa) is unrealistically low (min: 100 MPa)")
        elif ys > 3000:
            errors.append(f"❌ Yield Strength ({ys} MPa) is unrealistically high (max: 3000 MPa)")
    
    # 3. Tensile strength range check
    if uts > 0:
        if uts < 150:
            errors.append(f"❌ Tensile Strength ({uts} MPa) is unrealistically low (min: 150 MPa)")
        elif uts > 3500:
            errors.append(f"❌ Tensile Strength ({uts} MPa) is unrealistically high (max: 3500 MPa)")
    
    # 4. Elongation range check (0-60% is typical)
    if el > 0:
        if el < 0.1:
            errors.append(f"❌ Elongation ({el}%) is unrealistically low (min: 0.1%)")
        elif el > 100:
            errors.append(f"❌ Elongation ({el}%) cannot exceed 100%)")
    
    # 5. Density range check (Ni-based superalloys: 7-10 g/cm³)
    if density > 0:
        if density < 5.0:
            errors.append(f"❌ Density ({density} g/cm³) is too low for superalloys (min: 5.0 g/cm³)")
        elif density > 12.0:
            errors.append(f"❌ Density ({density} g/cm³) is too high for superalloys (max: 12.0 g/cm³)")
    
    # 6. Iterations check
    if iterations < 1:
        errors.append(f"❌ Iterations ({iterations}) must be at least 1")
    elif iterations > 20:
        errors.append(f"⚠️  Warning: {iterations} iterations is quite high (may take very long)")
    
    # 7. Check for conflicting requirements (high strength usually means low ductility)
    if ys > 1500 and el > 30:
        errors.append(f"⚠️  Warning: High YS ({ys} MPa) + High Elongation ({el}%) is difficult to achieve")
    
    return errors


def main():
    parser = argparse.ArgumentParser(description="AlloyMind Designer: Invent new superalloys.")
    parser.add_argument("--yield_strength", type=float, default=1000.0, help="Minimum Yield Strength (MPa)")
    parser.add_argument("--density", type=float, default=9.0, help="Maximum Density (g/cm³)")
    parser.add_argument("--temperature", type=float, default=900.0, help="Service temperature (°C). Room=20, High=900-1200")
    parser.add_argument("--processing", type=str, default="cast", choices=["cast", "wrought"],
                        help="Processing route: cast (default) or wrought")
    parser.add_argument("--iterations", type=int, default=3, 
                        help="Max iterations (1=quick, 3=balanced, 5=high quality). Stops early on success.")
    parser.add_argument("--composition", type=str, default=None, help="Starting composition as JSON (e.g. '{\"Ni\": 60, \"Al\": 5}')")
    
    args = parser.parse_args()
    
    # Validate inputs
    validation_errors = validate_design_inputs(
        args.yield_strength,
        0.0,  # tensile_strength removed
        0.0,  # elongation removed
        args.density,
        args.iterations
    )

    
    # Add temperature validation
    if args.temperature < -273:  # Absolute zero
        validation_errors.append(f"❌ Temperature ({args.temperature}°C) below absolute zero")
    elif args.temperature < 0:
        validation_errors.append(f"⚠️  Warning: Subzero temperature ({args.temperature}°C) is unusual for superalloys")
    elif args.temperature > 1500:
        validation_errors.append(f"❌ Temperature ({args.temperature}°C) exceeds superalloy limits (max: ~1500°C)")
    
    if validation_errors:
        print("\n" + "="*50)
        print("❌ INPUT VALIDATION FAILED")
        print("="*50)
        for error in validation_errors:
            print(error)
        print("="*50)
        sys.exit(1)
    
    print("==================================================")
    print(" 🧬 ALLOYMIND: AUTOMATED ALLOY DISCOVERY ENGINE 🧬")
    print("==================================================")
    print(f"🎯 TARGETS: Yield≥{args.yield_strength} MPa | Density≤{args.density} g/cm³")
    print(f"🌡️  TEMPERATURE: {args.temperature}°C | PROCESSING: {args.processing}")
    print("--------------------------------------------------")
    
    # Initialize implementation
    try:
        # Parse initial composition if provided
        start_comp = None
        import json
        if args.composition:
            start_comp = json.loads(args.composition)
            print(f"🧪 Starting with Custom Composition: {start_comp}")

        engine = IterativeDesignCrew({
            "Yield Strength": args.yield_strength,
            "Density": args.density
        })
        
        # Run Loop
        result = engine.loop(
            max_iterations=args.iterations, 
            start_composition=start_comp, 
            temperature=args.temperature,
            processing=args.processing
        )
        
        # Display final result
        print("\n" + "="*60)
        print(" 🏆 FINAL DESIGN RESULT")
        print("="*60)
        
        if "error" in result:
            print(f"❌ Design Failed: {result['error']}")
            if 'composition' in result:
                print(f"\n📝 Last Attempted Composition:")
                comp = result['composition']
                for elem, wt in sorted(comp.items(), key=lambda x: x[1], reverse=True):
                    print(f"  {elem}: {wt:.2f} wt%")
        else:
            # Classify design quality
            quality, quality_msg = engine._classify_design_quality(result)
            
            if quality == "OPTIMAL":
                print(f"✅ Design Converged Successfully! (Optimal Target Hit)\n")
            elif quality == "ACCEPTABLE":
                print(f"✅ Design Converged Successfully! (Slightly Over-Engineered)\n")
                print(f"   💡 {quality_msg}")
                print(f"   💡 Consider reducing expensive elements (Re, W, Ta) to lower cost\n")
            elif quality == "EXCESSIVE":
                print(f"⚠️ Design Over-Engineered\n")
                print(f"   {quality_msg}")
                print(f"   Recommendation: Reduce γ' formers (Al, Ti) or refractory elements (Re, W)\n")
            elif engine._is_design_successful(result):
                print(f"✅ Design Converged Successfully! (All Targets Met)\n")
            else:
                print(f"⚠️ Design Optimization Finished (Targets Not Fully Met)\n")
            
            print(f"📝 Final Composition ({result.get('processing', 'unknown')} processing):")
            comp = result['composition']
            for elem, wt in sorted(comp.items(), key=lambda x: x[1], reverse=True):
                print(f"  {elem}: {wt:.2f} wt%")
            
            print(f"\n📊 Predicted Properties:")
            props = result.get('properties', {})
            print(f"  Yield Strength: {props.get('Yield Strength', 'N/A')} MPa")
            print(f"  Tensile Strength: {props.get('Tensile Strength', 'N/A')} MPa")
            print(f"  Elongation: {props.get('Elongation', 'N/A')} %")
            print(f"  Density: {props.get('Density', 'N/A')} g/cm³")
            print(f"  Gamma Prime: {props.get('Gamma Prime', 'N/A')} vol%")
            
            print(f"\n⚠️  Physics Audit:")
            print(f"  TCP Risk: {result.get('tcp_risk', 'Unknown')}")
            print(f"  Penalty Score: {result.get('penalty_score', 0)}")
            
            if result.get('audit_penalties'):
                print(f"  Violations: {len(result['audit_penalties'])}")
                for penalty in result['audit_penalties'][:3]:
                    print(f"    - {penalty.get('name', 'Unknown')}: {penalty.get('reason', '')}")
            
            confidence = result.get('confidence', {})
            if isinstance(confidence, dict):
                print(f"\n🎯 Confidence: {confidence.get('level', 'UNKNOWN')} ({confidence.get('score', 0):.2f})")
            
            # Add physics explanations when targets not met
            if not engine._is_design_successful(result):
                print(f"\n💡 Physics Analysis:")
                tcp_risk = result.get('tcp_risk', 'Unknown')
                ys_achieved = props.get('Yield Strength', 0)
                ys_target = args.yield_strength
                
                # Analyze why it failed
                if tcp_risk == "High":
                    print(f"   • High TCP risk prevents achieving target strength")
                    print(f"   • Trade-off: Higher γ' (strength) → Higher Md (instability)")
                
                if ys_achieved < ys_target and ys_achieved > 0:
                    deficit = ys_target - ys_achieved
                    print(f"   • Yield Strength deficit: {deficit:.0f} MPa ({ys_achieved:.0f} < {ys_target:.0f})")
                
                # Suggest alternatives
                if args.processing == "cast":
                    print(f"\n💭 Consider Alternative Processing Route:")
                    print(f"   • --processing wrought (typically +10-15% strength)")
                elif args.processing == "wrought":
                    print(f"\n💭 Consider:")
                    print(f"   • --processing cast (easier manufacturing, slightly lower strength)")
                    print(f"   • Lower target if TCP risk is unacceptable")

            # Generate human-readable summary
            if result.get('explanation'):
                print(f"\n📖 Alloy Design Summary:")
                print(f"\n{result['explanation']}\n")
        
        print("="*60)

        
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    except Exception as e:
        import traceback
        print(f"\n❌ ERROR: {e}")
        print("\n📋 Traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
