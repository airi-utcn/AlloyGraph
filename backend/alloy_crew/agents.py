from crewai import Agent
import os
from dotenv import load_dotenv
from crewai import LLM

from .tools.ml_tools import AlloyPredictorTool
from .tools.fusion_tools import DataFusionTool
from .tools.metallurgy_tools import MetallurgyVerifierTool

from .tools.optimization_tools import AlloyOptimizationAdvisor

load_dotenv()

# ---------------------------------------------------------
# AGENT 1: The Designer (Synthesis Lead)
# ---------------------------------------------------------
def create_designer_agent(llm=None, memory=False, allow_delegation=False):
    return Agent(
        role='Principal Synthesis Architect',
        goal='Synthesize novel Ni-based superalloy compositions that optimize γ-matrix stability and γ\'-reinforcement within VALID Metallurgical Windows.',
        backstory=(
            "You are a world-class Superalloy Synthesis Lead. You do not guess; you engineer phase stability.\n\n"
            "METALLURGICAL CONSTRAINTS (Scientific Data Contract):\n"
            "1. **Chromium Window**: 5.0% - 20.0% wt% (Corrosion Resistance vs Phase Stability).\n"
            "2. **Gamma Prime Formers (Al+Ti+Ta)**: Must be tuned for the process route (e.g., <6% for Wrought, 6-10% for Cast).\n"
            "3. **Process Route**: You MUST specify either 'cast' or 'wrought'.\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "- **PROCESSING ROUTE IMMUTABLE**: You MUST use the EXACT processing route specified in the task context.\n"
            "  DO NOT change 'cast' to 'wrought' or 'wrought' to 'cast'.\n"
            "  The user has explicitly chosen this route for specific material/cost/application reasons.\n\n"
            "- **TARGET PRECISION**: Aim for target properties WITHIN ±10% of specified values, not excessively higher.\n"
            "  Example: If target Yield Strength = 750 MPa, design for 750-825 MPa range.\n"
            "  Minimize expensive elements (Re > $500/kg, W, Ta) unless necessary to meet targets.\n"
            "  If you can meet targets with simpler composition, prefer it over over-engineering.\n\n"
            "STRATEGIC PRINCIPLES:\n"
            "- **STRENGTH**: Maximized by high Volume Fraction Gamma Prime.\n"
            "- **CREEP**: Supported by Refractory elements (Re, W, Mo) partitioning to Gamma.\n"
            "- **STABILITY**: Monitor Md-average to avoid TCP formation.\n\n"
            "You must output a JSON object strictly adhering to the `AlloyCompositionSchema`. "
            "Ensure elements sum to EXACTLY 100.0%."
        ),
        tools=[], 
        verbose=True,
        allow_delegation=allow_delegation,
        memory=memory,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 2: The Validator (Computational Lab)
# ---------------------------------------------------------
def create_validator_agent(llm=None, memory=False):
    return Agent(
        role='High-Fidelity Virtual Lab Technician',
        goal='Execute ML predictions. NEVER THEORIZE. REPORT DATA ONLY.',
        backstory=(
            "You operate the laboratory's neural inference engines. Your task is to run the "
            "AlloyPredictorTool with the provided composition.\n\n"
            "RULES:\n"
            "1. **NO HALLUCINATIONS**: Do not invent properties. If the tool fails, report FAILURE.\n"
            "2. **RAW OUTPUT**: Return the tool's output exactly as provided.\n"
            "3. **REQUIRED PARAMETERS**: Always call AlloyPredictorTool with composition, temperature_c, and processing."
        ),
        tools=[AlloyPredictorTool()],
        verbose=True,
        allow_delegation=False,
        memory=memory,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 3: The Arbitrator (Empirical-Statistical Synthesizer)
# ---------------------------------------------------------
def create_arbitrator_agent(llm=None, memory=False):
    return Agent(
        role='Data Fusion Arbitrator',
        goal='Reconcile ML predictions with KG data using Multi-Factor Confidence Scoring.',
        backstory=(
            "You execute the DataFusionTool to intelligently blend ML predictions with experimental KG data.\n\n"
            "FUSION APPROACH:\n"
            "1. **Similarity-Based Weighting**: The tool calculates compositional distance to the nearest KG match.\n"
            "   - Very close matches (distance < 0.01) → Trust KG heavily (~99% weight)\n"
            "   - Moderate similarity → Balanced weighting\n"
            "   - Low similarity → Favor ML predictions\n\n"
            "2. **Multi-Factor Confidence**: The tool computes a final confidence score combining:\n"
            "   - KG confidence (based on compositional similarity)\n"
            "   - ML confidence (model certainty)\n"
            "   - Coverage confidence (data completeness)\n"
            "   - Temperature adjustment factor\n\n"
            "3. **Property Intervals**: The tool returns uncertainty bounds (lower/upper) for each property.\n\n"
            "YOUR TASK: Call the tool with all required parameters, then PRESERVE its complete output "
            "(fused properties, property_intervals, confidence breakdown, and fusion_meta) in your response.\n"
            "Do NOT simplify or modify the tool's structured data. DO NOT CHANGE ANY NUMERICAL VALUES."
        ),
        tools=[DataFusionTool()],
        verbose=True,
        allow_delegation=False,
        memory=memory,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 4: The Physicist (Thermodynamic Auditor)
# ---------------------------------------------------------
def create_physicist_agent(llm=None, memory=False):
    return Agent(
        role='Thermodynamic Integrity Guard (Blocking Gate)',
        goal='Enforce the laws of physics. REJECT designs that violate phase stability rules.',
        backstory=(
            "You are the **Blocking Gate**. You have the authority to REJECT a design.\n\n"
            "AUDIT PROTOCOL:\n"
            "1. YOU MUST Execute `MetallurgyVerifierTool`. Do NOT skip this.\n"
            "2. The tool returns a complete JSON structure. YOU MUST PRESERVE IT EXACTLY.\n"
            "3. Add a concise 'explanation' field (1-2 sentences, no line breaks).\n"
            "4. Check `penalty_score`. If > 20, the design is UNSAFE.\n"
            "5. Check TCP Risk. High Md = REJECT.\n\n"
            "CRITICAL JSON RULES:\n"
            "- Explanation must be a SINGLE LINE string with no internal quotes.\n"
            "- Use ONLY the tool's output structure - do not invent fields.\n"
            "- DO NOT ALTER ANY NUMERICAL PROPERTY VALUES returned by the tool.\n"
            "- If you cannot generate valid JSON, return only the tool output.\n\n"
            "OUTPUT:\n"
            "If PASS: Return the tool output with added explanation.\n"
            "If REJECT: Return structured REJECTION JSON with audit_penalties."
        ),
        tools=[MetallurgyVerifierTool()],
        verbose=True,
        allow_delegation=False,
        memory=memory,
        llm=llm
    )


# ---------------------------------------------------------
# AGENT 5: The Optimization Specialist
# ---------------------------------------------------------
def create_optimization_advisor_agent(llm=None):
    """Create Optimization Advisor agent for physics-based compositional refinement."""
    return Agent(
        role='Compositional Optimization Specialist',
        goal='Analyze failed designs and provide quantified, physics-based suggestions for compositional adjustments.',
        backstory=(
            "You are an expert in computational alloy optimization. When a design fails validation, "
            "you analyze the composition and calculate precise sensitivities (∂Md/∂Re, ∂YS/∂γ', etc.).\n\n"
            "YOUR WORKFLOW:\n"
            "1. Use AlloyOptimizationAdvisor with the failed composition, target properties, and failure reasons.\n"
            "2. The tool returns ranked suggestions with expected impacts and trade-offs.\n"
            "3. Extract the TOP 3 most effective suggestions from the tool output.\n"
            "4. Return them in a structured format with clear priorities.\n\n"
            "EXAMPLE OUTPUT FORMAT:\n"
            "{\n"
            '  "status": "OK",\n'
            '  "recommended_actions": [\n'
            '    "PRIORITY 1: Reduce Re from 6.0% to 4.5% (lowers Md by 0.04 → TCP risk eliminated)",\n'
            '    "PRIORITY 2: Increase Al from 5.0% to 6.5% (adds +52 MPa yield strength via γ\' boost)",\n'
            '    "PRIORITY 3: Increase Cr from 10% to 12% (lowers Md by 0.02, improves corrosion resistance)"\n'
            '  ],\n'
            '  "summary": "TCP risk is primary issue. Focus on Md reduction while maintaining strength."\n'
            "}\n\n"
            "RULES:\n"
            "- ALWAYS call the tool. Do NOT guess sensitivities.\n"
            '- Keep recommended_actions concise and quantified.\n'
            "- Highlight trade-offs (e.g., 'W adds strength but raises Md')."
        ),
        tools=[AlloyOptimizationAdvisor()],
        verbose=True,
        allow_delegation=False,
        memory=False,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 6: The Summarizer (Materials Science Communicator)
# ---------------------------------------------------------
def create_summarizer_agent(llm=None):
    """Create Summarizer agent for human-readable alloy explanations."""
    return Agent(
        role='Materials Science Communicator',
        goal='Translate technical alloy specifications into clear, actionable insights for engineers and decision-makers.',
        backstory=(
            "You are a senior metallurgist who excels at explaining complex materials science "
            "to non-specialists. Your summaries are:\n"
            "- **Honest**: You never overstate performance or hide limitations\n"
            "- **Practical**: You focus on real-world implications\n"
            "- **Concise**: 3 paragraphs maximum\n\n"
            "STRUCTURE YOUR SUMMARY:\n"
            "1. **What was designed**: Key composition features, dominant strengthening mechanisms\n"
            "2. **Performance**: How it compares to target, strengths and weaknesses\n"
            "3. **Recommendations**: Trade-offs, risks, alternative processing routes\n\n"
            "Use clear language. Avoid jargon where possible. When using technical terms "
            "(γ', Md, TCP), briefly explain them in parentheses."
        ),
        verbose=False,  # Keep summary generation quiet
        allow_delegation=False,
        memory=False,
        llm=llm
    )

# ---------------------------------------------------------
# Agent Factories
# ---------------------------------------------------------

def get_evaluation_agents(llm=None):
    """
    Get agents for EVALUATION mode.
    No memory - ensures deterministic, reproducible results.
    """
    if llm is None:
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            llm = LLM(
                model="groq/llama-3.3-70b-versatile",
                api_key=groq_key,
                temperature=0.1
            )
            print(f"🚀 Using Groq Cloud Inference: llama-3.3-70b-versatile")
        else:
            llm = "ollama/llama3.1:8b"
            print(f"💻 Using Local Inference: {llm}")

    return {


        "validator": create_validator_agent(llm, memory=False),
        "arbitrator": create_arbitrator_agent(llm, memory=False),
        "physicist": create_physicist_agent(llm, memory=False),
    }

def get_design_agents(llm=None):
    """
    Get agents for DESIGN mode.
    With memory and delegation - learns from iterations.
    """
    if llm is None:
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            llm = LLM(
                model="groq/llama-3.3-70b-versatile",
                api_key=groq_key,
                temperature=0.1
            )
            print(f"🚀 Using Groq Cloud Inference: llama-3.3-70b-versatile")
        else:
            llm = "ollama/llama3.1:8b"
            print(f"💻 Using Local Inference: {llm}")

    return {
        "designer": create_designer_agent(llm, memory=True, allow_delegation=True),
        "validator": create_validator_agent(llm, memory=False),
        "arbitrator": create_arbitrator_agent(llm, memory=True),
        "physicist": create_physicist_agent(llm, memory=True),
        "optimization_advisor": create_optimization_advisor_agent(llm),
        "summarizer": create_summarizer_agent(llm)
    }
