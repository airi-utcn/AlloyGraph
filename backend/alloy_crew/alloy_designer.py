import json
from typing import Optional

from crewai import Crew, Task

from .agents import get_design_agents
from .tools.rag_tools import AlloySearchTool
from .schemas import ValidationOutput, ArbitrationOutput, PhysicsAuditOutput, DesignOutput, OptimizationOutput


class IterativeDesignCrew:
    def __init__(self, target_props):
        self.target_props = target_props
        self.agents = get_design_agents()

        self.designer = self.agents["designer"]
        self.optimization_advisor = self.agents["optimization_advisor"]
        self.validator = self.agents["validator"]
        self.arbitrator = self.agents["arbitrator"]
        self.physicist = self.agents["physicist"]
        self.summarizer = self.agents["summarizer"]


        self.min_yield = float(target_props.get("Yield Strength", 0))
        self.min_tensile = float(target_props.get("Tensile Strength", 0))
        self.min_elongation = float(target_props.get("Elongation", 0))
        self.max_density = float(target_props.get("Density", 99.0))
        self.min_gamma_prime = float(target_props.get("Gamma Prime", 0))


        self._setup_tasks()
        self._setup_crews()

    def _setup_tasks(self):
        """Define tasks once with placeholders {variables} for dynamic execution."""


        self.task_design = Task(
            description=(
                "{base_comp_str}\n\n"
                "TARGETS (at {temperature}°C):\n"
                "{target_props_str}\n\n"
                "FEEDBACK FROM PREVIOUS RUN:\n"
                "{feedback}\n\n"
                "{novelty_msg}\n\n"
                "Task: Propose a BETTER composition that satisfies the targets.\n"
                "OUTPUT: Valid JSON with 'reasoning', 'composition', and 'processing'."
            ),
            expected_output="Valid structured output containing reasoning and composition.",
            output_pydantic=DesignOutput,
            agent=self.designer,
        )


        self.task_optimization = Task(
            description=(
                "The Designer's composition has failed validation.\n\n"
                "Composition: {composition_json}\n"
                "Target Properties: {target_props_str}\n"
                "Current Properties: {current_props_json}\n"
                "Failure Reasons: {failure_reasons}\n"
                "Processing: {processing}\n\n"
                "Use AlloyOptimizationAdvisor to calculate physics-based suggestions.\n"
                "Return the TOP 3 most effective adjustments with quantified impacts."
            ),
            expected_output="Structured optimization suggestions with priorities and expected impacts.",
            output_pydantic=OptimizationOutput,
            agent=self.optimization_advisor,
            context=[self.task_design],
        )


        self.task_validation = Task(
            description=(
                "Validate composition at {temperature}°C using AlloyPredictorTool.\n"
                "Processing: {processing}\n"
                "Composition: {composition_json}\n\n"
                "Call the tool with composition, temperature_c, and processing parameters."
            ),
            expected_output="Structured ML predictions with confidence.",
            output_pydantic=ValidationOutput,
            agent=self.validator,
            async_execution=False,
        )

        self.task_arbitration = Task(
            description=(
                "Knowledge Graph Context:\n{kg_context}\n\n"
                "Processing: {processing}\n"
                "Take ML predictions from Validator. Run DataFusionTool to anchor against KG.\n"
                "Use mode='design' for fusion (trust ML more for innovation at {temperature}°C).\n"
                "PRESERVE property_intervals and confidence breakdown."
            ),
            expected_output="Fused properties with confidence and intervals.",
            output_pydantic=ArbitrationOutput,
            agent=self.arbitrator,
            context=[self.task_validation],
        )

        self.task_physics = Task(
            description=(
                "Take:\n"
                "1) Composition: {composition_json}\n"
                "2) Processing: {processing}\n"
                "3) Anchored properties from Arbitrator\n\n"
                "Run MetallurgyVerifierTool. Generate physics-based explanation.\n"
                "PRESERVE property_intervals and confidence data.\n"
                "Generate detailed explanation of strengthening mechanisms and suitability."
            ),
            expected_output="Final audit with explanation and intervals.",
            output_pydantic=PhysicsAuditOutput,
            agent=self.physicist,
            context=[self.task_arbitration],
        )

    def _setup_crews(self):
        """Instantiate Crews once."""
        self.crew_synthesis = Crew(
            agents=[self.designer],
            tasks=[self.task_design],
            verbose=True,
        )

        self.crew_analysis = Crew(
            agents=[self.validator, self.arbitrator, self.physicist],
            tasks=[self.task_validation, self.task_arbitration, self.task_physics],
            verbose=True,
        )

    def _run_novelty_check(self, composition: Optional[dict]) -> str:
        if not composition:
            return ""
        try:
            search_tool = AlloySearchTool()
            rag_result = search_tool._run(composition=composition, limit=1)
            if rag_result and "Error" not in str(rag_result):
                rag_data = json.loads(rag_result)
                if isinstance(rag_data, list) and len(rag_data) > 0:
                    match = rag_data[0]
                    name = match.get("name", "Unknown")
                    return f" [Context: Closest match is **{name}**. If different, this is a NOVEL design.]"
        except Exception:
            pass
        return ""

    def run(self, base_composition=None, input_feedback="", temperature=900, processing="cast"):
        """Run one iteration of Design (Phase 1) → Validate (Phase 2)."""


        base_comp_str = (
            f"Starting Composition: {json.dumps(base_composition)}"
            if base_composition
            else "No starting comp - create from scratch"
        )

        target_str = (
            f"- Yield Strength > {self.min_yield} MPa\n"
            f"- Tensile Strength > {self.min_tensile} MPa\n"
            f"- Elongation > {self.min_elongation} %\n"
            f"- Density < {self.max_density} g/cm3\n"
            f"- Gamma Prime > {self.min_gamma_prime} %"
        )

        novelty_msg = self._run_novelty_check(base_composition)

        inputs_synthesis = {
            "base_comp_str": base_comp_str,
            "target_props_str": target_str,
            "feedback": input_feedback or "None (Initial Run)",
            "temperature": temperature,
            "processing": processing,
            "novelty_msg": novelty_msg,
        }


        try:
            self.crew_synthesis.kickoff(inputs=inputs_synthesis)
        except Exception as e:
            return {"error": f"Synthesis Crew Failed: {e}"}


        try:
            d_obj = getattr(self.task_design.output, "pydantic", None)
            if not d_obj:
                return {"error": "Designer failed to return structured output."}
            designer_comp = d_obj.composition
            processed_route = d_obj.processing
            
            # HARD VALIDATION: Enforce user-specified processing
            if processed_route != processing:
                print(f"⚠️  PROCESSING MISMATCH DETECTED!")
                print(f"   User specified: {processing}")
                print(f"   Designer outputted: {processed_route}")
                print(f"   FORCING: {processing} (user choice is IMMUTABLE)")
                processed_route = processing  # Override LLM's choice
        except Exception:
            return {"error": "Designer output extraction failed."}


        try:
            kg_raw = AlloySearchTool()._run(composition=designer_comp, limit=3)
            try:
                kg_json = json.loads(kg_raw)  # ensure it's valid json
                kg_context = json.dumps(kg_json)
            except Exception:
                kg_context = "[]"
        except Exception:
            kg_context = "[]"

        novelty_new_design = self._run_novelty_check(designer_comp)


        inputs_analysis = {
            "composition_json": json.dumps(designer_comp),
            "temperature": temperature,
            "processing": processed_route,
            "kg_context": kg_context,
        }


        try:
            self.crew_analysis.kickoff(inputs=inputs_analysis)
        except Exception as e:
            return {"error": f"Analysis Crew Failed: {e}"}


        physics_output = getattr(self.task_physics.output, "pydantic", None)
        if not physics_output:
            return {"error": "Physicist did not return structured output."}

        # --- ANTI-HALLUCINATION: Validate properties against ground truth ---
        validator_output = getattr(self.task_validation.output, "pydantic", None)
        if validator_output and hasattr(validator_output, 'ml_prediction'):
            ml_truth = validator_output.ml_prediction  # Ground truth from ML tool
            

            for prop_name in ["Yield Strength", "Tensile Strength", "Elongation", "Density"]:
                if prop_name in ml_truth and prop_name in physics_output.properties:
                    ml_value = ml_truth[prop_name]
                    phys_value = physics_output.properties[prop_name]
                    

                    if abs(phys_value - ml_value) > max(0.1 * ml_value, 10):  # 10% or 10 units
                        print(f"⚠️  Corrected hallucinated {prop_name}: {phys_value:.1f} → {ml_value:.1f}")
                        physics_output.properties[prop_name] = ml_value

        # Generate comprehensive summary using Summarizer Agent
        try:
            summarizer = self.summarizer  # Use from __init__
            comp_str = ", ".join([f"{elem}: {wt:.1f}%" for elem, wt in sorted(designer_comp.items(), key=lambda x: x[1], reverse=True)[:5]])
            
            summary_task = Task(
                description=(
                    f"Generate a 3-paragraph summary for this alloy design:\n\n"
                    f"**Target**: Yield Strength ≥ {self.min_yield} MPa, Density ≤ {self.max_density} g/cm³\n\n"
                    f"**Designed Composition**: {comp_str}, ...\n\n"
                    f"**Achieved Properties**:\n"
                    f"- Yield Strength: {physics_output.properties.get('Yield Strength', 'N/A')} MPa\n"
                    f"- Tensile Strength: {physics_output.properties.get('Tensile Strength', 'N/A')} MPa\n"
                    f"- Elongation: {physics_output.properties.get('Elongation', 'N/A')}%\n"
                    f"- Gamma Prime: {physics_output.properties.get('Gamma Prime', 'N/A')} vol%\n\n"
                    f"**Physics Audit**:\n"
                    f"- TCP Risk: {physics_output.tcp_risk}\n"
                    f"- Violations: {len(physics_output.audit_penalties)}\n\n"
                    f"Explain (1) What was designed, (2) Performance vs target, (3) Trade-offs and recommendations."
                ),
                expected_output="3-paragraph technical summary in clear language",
                agent=summarizer
            )
            
            summary_crew = Crew(
                agents=[summarizer],
                tasks=[summary_task],
                verbose=False
            )
            
            summary_result = summary_crew.kickoff()
            summary_text = str(summary_result.raw) if hasattr(summary_result, 'raw') else str(summary_result)
            
        except Exception as e:
            print(f"⚠️  Could not generate summary: {e}")
            summary_text = physics_output.explanation  # Fallback to physicist explanation

        return {
            "composition": designer_comp,
            "processing": processed_route,
            "properties": physics_output.properties,
            "property_intervals": physics_output.property_intervals,
            "metallurgy_metrics": physics_output.metallurgy_metrics,
            "confidence": physics_output.confidence,
            "explanation": summary_text,
            "novelty": novelty_new_design,
            "penalty_score": physics_output.penalty_score,
            "tcp_risk": physics_output.tcp_risk,
            "audit_penalties": [p.dict() for p in physics_output.audit_penalties] if physics_output.audit_penalties else [],
        }


    def _is_design_successful(self, result):
        if result.get("error"):
            return False


        if result.get("tcp_risk", "High") == "High":
            return False


        penalties = result.get("audit_penalties", [])
        if any(p.get("name") == "High Md" for p in penalties):
            return False


        props = result.get("properties", {})

        if self.min_yield > 0 and float(props.get("Yield Strength", 0) or 0) < self.min_yield:
            return False
        if self.min_tensile > 0 and float(props.get("Tensile Strength", 0) or 0) < self.min_tensile:
            return False
        if self.min_elongation > 0 and float(props.get("Elongation", 0) or 0) < self.min_elongation:
            return False
        if self.max_density < 99.0 and float(props.get("Density", 1e9) or 1e9) > self.max_density:
            return False
        if self.min_gamma_prime > 0 and float(props.get("Gamma Prime", 0) or 0) < self.min_gamma_prime:
            return False

        return True

    def _classify_design_quality(self, result):
        """Classify design quality based on how well it hits targets."""
        if result.get("error") or not self._is_design_successful(result):
            return "FAILED", ""
        
        props = result.get("properties", {})
        ys = float(props.get("Yield Strength", 0) or 0)
        

        if self.min_yield > 0 and ys > 0:
            target = self.min_yield
            optimal_max = target * 1.10  # +10% overshoot acceptable
            excessive_threshold = target * 1.30  # +30% excessive
            overshoot_pct = ((ys / target) - 1) * 100
            
            if target <= ys <= optimal_max:
                return "OPTIMAL", f"Target hit within optimal range ({ys:.0f} MPa, +{overshoot_pct:.1f}%)"
            elif optimal_max < ys <= excessive_threshold:
                return "ACCEPTABLE", f"Over-engineered: {ys:.0f} MPa (+{overshoot_pct:.0f}% above {target} MPa target)"
            elif ys > excessive_threshold:
                return "EXCESSIVE", f"Significantly over-engineered: {ys:.0f} MPa (+{overshoot_pct:.0f}% above target)"
        
        return "SUCCESS", ""

    def loop(self, max_iterations=3, start_composition=None, temperature=900, processing="cast"):
        current_comp = start_composition
        feedback = ""
        result = {"error": "No iterations executed."}
        use_direct_application = False  # Flag for deterministic mode

        for i in range(max_iterations):
            iteration_num = i + 1
            print(f"\n⚡ ITERATION {iteration_num}/{max_iterations}")

            # DIRECT APPLICATION MODE: Skip LLM after iteration 1 if we have adjusted comp
            if use_direct_application and current_comp:
                print("🔬 DIRECT APPLICATION MODE: Using physics-optimized composition directly (bypassing LLM)")
                result = {
                    "composition": current_comp,
                    "processing": processing,
                    "reasoning": "Direct application of physics-based optimization"
                }


                inputs_validation = {
                    "composition_json": json.dumps(current_comp),
                    "temperature": temperature,
                    "processing": processing,
                    "kg_context": "[]",
                }
                try:
                    self.crew_analysis.kickoff(inputs=inputs_validation)

                    val_output = getattr(self.task_validation.output, "pydantic", None)
                    if val_output:
                        result["predicted_props"] = val_output.ml_prediction  # FIXED: use correct attribute
                        result["properties"] = val_output.ml_prediction # CRITICAL: Downstream uses this
                    

                    phys_output = getattr(self.task_physics.output, "pydantic", None)
                    if phys_output:
                        # ANTI-HALLUCINATION: Use ML ground truth, not LLM modifications
                        if val_output and hasattr(val_output, 'ml_prediction'):
                            ml_truth = val_output.ml_prediction
                            for prop_name in ["Yield Strength", "Tensile Strength", "Elongation", "Density"]:
                                if prop_name in ml_truth:
                                    result["properties"][prop_name] = ml_truth[prop_name]
                        
                        result["tcp_risk"] = phys_output.tcp_risk

                        result["audit_penalties"] = [p.model_dump() for p in phys_output.audit_penalties]
                    else:

                        raw_phys = getattr(self.task_physics.output, "raw", "")
                        if raw_phys:
                             try:
                                phys_data = json.loads(raw_phys)
                                result["tcp_risk"] = phys_data.get("tcp_risk", "Unknown")
                                result["audit_penalties"] = phys_data.get("audit_penalties", [])
                             except:
                                pass
                except Exception as e:
                    print(f"⚠️ Validation error in direct mode: {e}")
                    use_direct_application = False  # Fall back to LLM
            
            if not use_direct_application or not current_comp:

                result = self.run(
                    base_composition=current_comp,
                    input_feedback=feedback,
                    temperature=temperature,
                    processing=processing,
                )

            if "error" in result:
                print(f"❌ Aborted: {result['error']}")

                # IMPORTANT FIX: advance current_comp when possible so iteration uses the failing proposal
                current_comp = result.get("composition", current_comp)

                feedback = f"Design Failed: {result['error']}. Fix constraints."

                if "Chemistry" in result["error"]:
                    continue
                break

            print(f"   Proposed: {result['composition']}")
            props = result.get("properties", {})
            tcp = result.get("tcp_risk", "Unknown")
            penalties = len(result.get("audit_penalties", []))
            print(f"   Properties: YS={props.get('Yield Strength', 0)}, TCP={tcp}, Penalties={penalties}")


            if self._is_design_successful(result):
                print("\n✅ SUCCESS! Converged.")
                break


            failures = []
            if self.min_yield > 0 and props.get("Yield Strength", 0) < self.min_yield:
                failures.append(f"Yield Strength too low ({props.get('Yield Strength')} < {self.min_yield})")
            if self.min_tensile > 0 and props.get("Tensile Strength", 0) < self.min_tensile:
                failures.append(f"Tensile Strength too low ({props.get('Tensile Strength')} < {self.min_tensile})")
            if self.min_elongation > 0 and props.get("Elongation", 0) < self.min_elongation:
                failures.append(f"Elongation too low ({props.get('Elongation')} < {self.min_elongation})")
            if self.max_density < 99.0 and props.get("Density", 1e9) > self.max_density:
                failures.append(f"Density too high ({props.get('Density')} > {self.max_density})")
            if self.min_gamma_prime > 0 and props.get("Gamma Prime", 0) < self.min_gamma_prime:
                failures.append(f"Gamma Prime too low ({props.get('Gamma Prime')} < {self.min_gamma_prime})")

            if tcp == "High":
                failures.append("TCP Risk is HIGH")
            if penalties > 0:
                failures.append(f"{penalties} Physics Violation(s)")

            # --- PRIORITY ENFORCEMENT LOGIC ---
            # Once YS target is met, focus EXCLUSIVELY on TCP risk
            ys_target_met = props.get("Yield Strength", 0) >= self.min_yield if self.min_yield > 0 else True
            tcp_critical = tcp == "High" or tcp == "Medium"
            
            if ys_target_met and tcp_critical:
                # PRIORITY MODE: Only focus on TCP, ignore other property improvements
                print("\n⚡ PRIORITY MODE: YS target met ({:.0f} >= {:.0f} MPa). Focusing ONLY on TCP risk reduction.".format(
                    props.get("Yield Strength", 0), self.min_yield))
                

                tcp_failures = [f for f in failures if "TCP" in f or "Md" in f or "Physics" in f]
                failures_for_advisor = tcp_failures if tcp_failures else ["TCP Risk needs reduction"]
                
                priority_note = (
                    "\n\n⚠️ CRITICAL PRIORITY: YS target already achieved. "
                    "Do NOT attempt to improve yield strength further. "
                    "Focus EXCLUSIVELY on reducing TCP risk by lowering Md. "
                    "Accept slight YS reduction if it eliminates TCP risk."
                )
            else:
                failures_for_advisor = failures
                priority_note = ""
            


            try:
                target_str = (
                    f"- Yield Strength > {self.min_yield} MPa\n"
                    f"- Tensile Strength > {self.min_tensile} MPa\n"
                    f"- Elongation > {self.min_elongation} %\n"
                    f"- Density < {self.max_density} g/cm3\n"
                    f"- Gamma Prime > {self.min_gamma_prime} %"
                )
                
                optimization_inputs = {
                    "composition_json": json.dumps(result["composition"]),
                    "target_props_str": target_str,
                    "current_props_json": json.dumps(props),
                    "failure_reasons": json.dumps(failures_for_advisor),  # Use filtered failures
                    "processing": processing,
                }
                

                crew_opt = Crew(
                    agents=[self.optimization_advisor],
                    tasks=[self.task_optimization],
                    verbose=True,
                )
                crew_opt.kickoff(inputs=optimization_inputs)
                

                opt_output = getattr(self.task_optimization.output, "pydantic", None)
                if opt_output and opt_output.recommended_actions:
                    print("\n📊 OPTIMIZATION SUGGESTIONS:")
                    for action in opt_output.recommended_actions[:3]:
                        print(f"   • {action}")
                    
                    

                    failure_list = ', '.join(failures_for_advisor)
                    suggestions_text = "\n".join(f"  • {action}" for action in opt_output.recommended_actions[:5])
                    feedback = (
                        f"Design REJECTED: {failure_list}\n\n"
                        f"OPTIMIZATION SUGGESTIONS FROM PHYSICS ANALYSIS:\n{suggestions_text}\n\n"
                        f"Propose a NEW composition addressing these issues.\n"
                        f"Use your metallurgical expertise to incorporate these suggestions intelligently.{priority_note}"
                    )
                else:
                    feedback = f"Design FAILED: {', '.join(failures)}. Propose a new composition to fix these issues."
            except Exception as e:
                print(f"⚠️  Optimization advisor error: {e}")
                failure_str = ", ".join(failures) if failures else "unspecified issues"
                feedback = f"Design FAILED: {failure_str}. Propose a new composition to fix these issues."



        return result


if __name__ == "__main__":
    loop = IterativeDesignCrew({"Yield Strength": 1100})
    loop.loop(max_iterations=2)
