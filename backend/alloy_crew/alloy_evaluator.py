from typing import Dict, Any, List, Optional, Union, Literal
import json
from crewai import Task, Crew, Process
from .agents import get_agents
from .tools.rag_tools import AlloySearchTool
from pydantic import BaseModel, Field


class ValidationOutput(BaseModel):
    status: Literal["OK", "FAIL"]
    temperature_c: int
    composition_wt_percent: Dict[str, float]
    ml_prediction: Dict[str, Any]
    errors: List[str] = []

class FusionMeta(BaseModel):
    kg_similarity_max: float = 0.0
    ml_weight: float = 0.0
    kg_weight: float = 0.0
    data_conflict: bool = False
    is_kg_anchored: bool = False

class ArbitrationOutput(BaseModel):
    status: str
    summary: str = Field("", description="Summary of Data Fusion (e.g. contains 'Anchoring')")
    processing: Literal["cast", "wrought", "unknown"] = Field(..., description="Alloy processing type (cast/wrought)")
    penalty_score: float
    tcp_risk: str
    properties: Dict[str, Any]
    property_intervals: Dict[str, Any] = Field(default_factory=dict, description="Uncertainty intervals for properties")
    metallurgy_metrics: Dict[str, Any] = {}
    fusion_meta: FusionMeta
    confidence: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = []

class AuditPenalty(BaseModel):
    name: str
    value: Union[float, str]
    reason: str

class PhysicsAuditOutput(BaseModel):
    status: Literal["PASS", "REJECT", "FAIL"]
    processing: str = Field(..., description="Alloy processing type (cast/wrought/unknown)")
    penalty_score: float = 0.0
    tcp_risk: str = "LOW"
    properties: Dict[str, Any]
    property_intervals: Dict[str, Any] = Field(default_factory=dict, description="Uncertainty intervals for properties")
    metallurgy_metrics: Dict[str, Any]
    audit_penalties: List[AuditPenalty] = []
    recommended_repairs: List[str] = []
    errors: List[str] = []
    confidence: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""

class AlloyEvaluationCrew:
    def __init__(self, llm_config=None):
        # Initialize agents with optional local LLM config
        self.agents_map = get_agents(llm=llm_config)
        self.validator = self.agents_map['validator']
        self.arbitrator = self.agents_map['arbitrator']
        self.physicist = self.agents_map['physicist']

    @staticmethod
    def validate_composition(composition: Dict[str, float]) -> Dict[str, Any]:
        """
        Validates and cleans composition by removing non-positive values.
        Returns dict with cleaned composition and any validation warnings.
        """
        warnings = []
        
        # Remove non-positive values
        cleaned = {k: max(0.0, float(v)) for k, v in composition.items() if float(v) > 0}
        
        if not cleaned:
            raise ValueError("Composition is empty after removing non-positives.")

        total = sum(cleaned.values())
        
        # Trust user input if close to 100%
        if 99.5 <= total <= 100.5:
            return {"composition": cleaned, "warnings": warnings}
        
        # Collect warnings for significant deviations
        if total < 95.0:
            warnings.append(f"Composition sums to {total:.1f}%, which seems incomplete. Consider adding missing elements.")
        elif total > 105.0:
            warnings.append(f"Composition sums to {total:.1f}%, which exceeds 100%. This may indicate an error.")
        elif abs(total - 100.0) > 2.0:
            warnings.append(f"Composition sums to {total:.1f}% (expected ~100%).")
        
        # Reject if total is way off
        if total < 90.0 or total > 110.0:
            raise ValueError(
                f"Composition total ({total:.1f}%) is outside acceptable range (90-110%). "
                f"Please check your input values."
            )

        return {
            "composition": {k: round(v, 3) for k, v in cleaned.items()},
            "warnings": warnings
        }
            
            
    def run(self, composition: dict, processing: str = "wrought", temperature: int = 900) -> Dict[str, Any]:
        """
        Runs the Physics Audit evaluation.
        Args:
            composition: Dict of element wt%.
            processing: Alloy processing hint.
            temperature: Target temp in C.
        """
        try:
            validation_result = self.validate_composition(composition)
            current_comp = validation_result["composition"]
        except Exception as e:
            return {"status": "FAIL", "stage": "validation", "error": str(e)}
        
        # 0. KG Context (Pre-Agent Lookup for robustness)
        try:
            search_tool = AlloySearchTool() 
            kg_context_str = search_tool._run(composition=current_comp, limit=10)
        except Exception as e:
            return {"status": "FAIL", "stage": "kg_lookup", "error": str(e)}

        comp_json = json.dumps(current_comp, ensure_ascii=False)
        
        # --- TASK 1: VALIDATION ---
        task_validation = Task(
            description=(
                f"Validate composition at {temperature}°C using AlloyPredictorTool.\n"
                f"Composition: {comp_json}\n"
                f"Processing: {processing}\n\n"
                "Call the tool with composition, temperature_c, and processing parameters."
            ),
            expected_output="Valid structured output validating the alloy composition.",
            output_pydantic=ValidationOutput,
            agent=self.validator
        )

        # --- TASK 2: ARBITRATION ---
        task_arbitration = Task(
            description=(
                f"Arbitrate ML vs KG.\n"
                f"KG Context: {kg_context_str}\n"
                f"Target Temp: {temperature}°C\n"
                f"Processing: {processing}\n"
                f"Composition: {comp_json}\n"
                "Input: Use the 'ml_prediction' from the Validator's output.\n\n"
                "REQUIREMENTS:\n"
                "1. Call `DataFusionTool` with `composition` (as JSON object), `ml_prediction_json`, `rag_context` (from KG Context above), `target_temperature_c`, and `processing`.\n"
                "2. The Tool Output contains fused properties AND property_intervals.\n"
                "3. CRITICAL: You MUST use the values from the Tool Output. Do not use the ML Input values if they differ.\n"
                "4. PRESERVE the `property_intervals` object EXACTLY as returned by the tool (as a dictionary of lower/upper/uncertainty blocks, NOT lists).\n"
                "5. PRESERVE the `confidence` object EXACTLY as returned (including breakdown, kg_weight, etc).\n"
                "6. Return the structured output as defined."
            ),
            expected_output="Valid structured output with fused properties.",
            output_pydantic=ArbitrationOutput,
            agent=self.arbitrator,
            context=[task_validation]
        )

        # --- TASK 3: PHYSICS AUDIT ---
        task_physics = Task(
            description=(
                "Evaluate physical validity.\n"
                f"Composition: {comp_json}\n"
                "Input: Use the COMPLETE Arbitrator output JSON (including fusion_meta).\n\n"
                "1. ANALYZE THE ALLOY TYPE (LLM REASONING):\n"
                "   - If Cr > 21.0%: likely corrosion-resistant → Set alloy_type='high_corrosion'\n"
                "   - If Cr < 20.0% AND (Ti + Al) > 4.0%: likely high-strength blade → Set alloy_type='high_strength'\n"
                "   - Otherwise: Set alloy_type='standard'\n"
                "2. EXECUTE `MetallurgyVerifierTool` with `composition` AND `anchored_properties_json`.\n"
                "   - IMPORTANT: `anchored_properties_json` MUST be the ENTIRE JSON object you received as input (containing `properties`, `property_intervals`, `fusion_meta`, `confidence` etc.) serialized as a string.\n"
                "   - Do NOT just pass the properties dictionary. Pass the keys 'property_intervals' and 'confidence' unmodified.\n"
                    "   - Pass your inferred `alloy_type`.\n"
                    "3. The tool returns verified_properties, property_intervals, confidence, and metallurgy metrics.\n"
                    "4. GENERATE EXPERT METALLURGICAL INSIGHT (3-5 sentences):\n"
                    "   - ACT AS A SENIOR PHYSICIST: Use your deep domain knowledge to interpret the results uniquely for THIS specific alloy.\n"
                    "   - NO TEMPLATES: Do not use rigid sentence structures. Explain what matters most for this composition.\n"
                "   - KEY GUIDELINES:\n"
                    "     • Identify the dominant strengthening mechanism (Gamma Prime vs Solid Solution) and explain its implication.\n"
                    "     • Evaluate the trade-offs (e.g., 'High strength but likely lower ductility...').\n"
                    "     • Propose specific real-world applications based on the property profile (e.g., 'Ideal for turbine discs', 'Suitable for combustor liners').\n"
                    "     • Contextualize the confidence naturally (e.g., '...supported by close matches in our experimental dataset' or '...an exploratory composition requiring validation').\n"
                    "   - TONE: Professional, insightful, and variable. Avoid 'AI-sounding' repetition. NO IT JARGON (KG, ML, Data Source).\n"
                    "5. UPDATE THE TOOL OUTPUT: Replace the empty 'explanation' field with your generated explanation.\n"
                    "6. CRITICAL: Output the tool's JSON with your explanation added.\n"
                    "   - Do NOT modify verified_properties, property_intervals, or confidence\n"
                    "   - Ensure 'property_intervals' matches the tool output EXACTLY (do not simplify to lists)\n"
                    "   - ONLY update explanation field"
            ),
            expected_output="Valid structured output with physics audit results.",
            output_pydantic=PhysicsAuditOutput,
            agent=self.physicist,
            context=[task_arbitration]
        )

        # Create and run crew
        evaluation_crew = Crew(
            agents=[self.validator, self.arbitrator, self.physicist],
            tasks=[task_validation, task_arbitration, task_physics],
            process=Process.sequential,
            verbose=True
        )

        try:
            crew_output = evaluation_crew.kickoff()
            
            # Extract structured output
            physics_output = None
            if hasattr(crew_output, "pydantic") and crew_output.pydantic:
                physics_output = crew_output.pydantic
            elif hasattr(crew_output, "raw"):
                # Fallback: attempt manual parse
                try:
                    data = json.loads(crew_output.raw)
                    physics_output = PhysicsAuditOutput(**data)
                except:
                    raise ValueError(f"Failed to get Pydantic output. Raw: {crew_output.raw}")
            else:
                # Check if it's the object directly
                physics_output = crew_output
                if not isinstance(physics_output, PhysicsAuditOutput):
                    # Try task output
                    last_task_output = task_physics.output
                    if last_task_output and last_task_output.pydantic:
                        physics_output = last_task_output.pydantic
                    else:
                        raise ValueError("Could not retrieve structured output from Physics task.")

        except Exception as e:
            return {"status": "FAIL", "stage": "crew_execution", "error": str(e)}

        return physics_output.model_dump()
