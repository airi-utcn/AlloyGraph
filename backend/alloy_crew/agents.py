from crewai import Agent
import os
from dotenv import load_dotenv
from crewai import LLM
from .tools.rag_tools import AlloySearchTool
from .tools.ml_tools import AlloyPredictorTool
from .tools.fusion_tools import DataFusionTool
from .tools.metallurgy_tools import MetallurgyVerifierTool
from .tools.design_tools import CompositionVerifierTool

load_dotenv()

# ---------------------------------------------------------
# AGENT 1: The Researcher (Knowledge Graph Architect)
# ---------------------------------------------------------
def create_researcher_agent(llm=None):
    return Agent(
        role='Metallurgical Knowledge Architect',
        goal='Analyze the Alloy Knowledge Graph to identify historical precedents and empirical benchmarks.',
        backstory=(
            "You are a specialist in metallurgical informatics. Your mission is to bridge the gap between "
            "experimental history and modern design. When provided with a composition, you query the "
            "AlloySearchTool to unearth the most similar existing alloys.\n\n"
            "Your output is the foundational 'ground truth' for the design team. You must explain why "
            "the found alloys are relevant (e.g., matching processing methods like Cast or Wrought). "
            "Ensure you provide tool results faithfully without technical metadata."
        ),
        tools=[AlloySearchTool()],
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 2: The Designer (Synthesis Lead)
# ---------------------------------------------------------
def create_designer_agent(llm=None):
    return Agent(
        role='Principal Synthesis Architect',
        goal='Synthesize novel Ni-based superalloy compositions that optimize γ-matrix stability and γ\'-reinforcement within VALID Metallurgical Windows.',
        backstory=(
            "You are a world-class Superalloy Synthesis Lead. You do not guess; you engineer phase stability.\n\n"
            "METALLURGICAL CONSTRAINTS (Scientific Data Contract):\n"
            "1. **Chromium Window**: 5.0% - 20.0% wt% (Corrosion Resistance vs Phase Stability).\n"
            "2. **Gamma Prime Formers (Al+Ti+Ta)**: Must be tuned for the process route (e.g., >8% for Single Crystal, <6% for Wrought).\n"
            "3. **Process Route**: You MUST specify the route (e.g., 'single_crystal', 'wrought').\n\n"
            "STRATEGIC PRINCIPLES:\n"
            "- **STRENGTH**: Maximized by high Volume Fraction Gamma Prime.\n"
            "- **CREEP**: Supported by Refractory elements (Re, W, Mo) partitioning to Gamma.\n"
            "- **STABILITY**: Monitor Md-average to avoid TCP formation.\n\n"
            "You must output a JSON object strictly adhering to the `AlloyCompositionSchema`. "
            "Ensure elements sum to EXACTLY 100.0%."
        ),
        tools=[CompositionVerifierTool()], 
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 3: The Validator (Computational Lab)
# ---------------------------------------------------------
def create_validator_agent(llm=None):
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
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 4: The Arbitrator (Empirical-Statistical Synthesizer)
# ---------------------------------------------------------
def create_arbitrator_agent(llm=None):
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
            "Do NOT simplify or modify the tool's structured data."
        ),
        tools=[DataFusionTool()],
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

# ---------------------------------------------------------
# AGENT 5: The Physicist (Thermodynamic Auditor)
# ---------------------------------------------------------
def create_physicist_agent(llm=None):
    return Agent(
        role='Thermodynamic Integrity Guard (Blocking Gate)',
        goal='Enforce the laws of physics. REJECT designs that violate phase stability rules.',
        backstory=(
            "You are the **Blocking Gate**. You have the authority to REJECT a design.\n\n"
            "AUDIT PROTOCOL:\n"
            "1. YOU MUST Execute `MetallurgyVerifierTool`. Do NOT skip this.\n"
            "2. Check `penalty_score`. If > 20 (arbitrary units), the design is UNSAFE.\n"
            "3. Check TCP Risk. High Md = REJECT.\n\n"
            "OUTPUT:\n"
            "If PASS: Return the Final Report.\n"
            "If REJECT: Return a structured 'REJECTION' JSON with specific 'audit_penalties' "
            "so the Designer can fix it."
        ),
        tools=[MetallurgyVerifierTool()],
        verbose=True,
        allow_delegation=False,
        llm=llm
    )


def get_agents(llm=None):
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
        "researcher": create_researcher_agent(llm),
        "designer": create_designer_agent(llm),
        "validator": create_validator_agent(llm),
        "arbitrator": create_arbitrator_agent(llm),
        "physicist": create_physicist_agent(llm)
    }
