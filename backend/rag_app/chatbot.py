import os
import re
import logging
from typing import List, Tuple, Optional
import chainlit as cl
from chainlit.input_widget import Select, Slider, Switch
import ollama

try:
    from rag_system import SuperalloyRAG
    RAG_CLASS = SuperalloyRAG
except ImportError:
    # Fallback for relative import if run as module
    from .rag_system import SuperalloyRAG
    RAG_CLASS = SuperalloyRAG
except Exception as e:
    logging.error(f"Could not import RAG system: {e}")
    RAG_CLASS = None

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("superalloy_chainlit")

# ----- UI config -----
DEFAULT_MODEL = os.getenv("LLM_MODEL", "llama3.2")
DEFAULT_TEMPERATURE = float(os.getenv("UI_TEMPERATURE", "0.2"))
MAX_HISTORY = 5

STARTERS = [
    ("Alloy Composition", "What is the composition of Inconel 718?", "/public/idea.svg"),
    ("Properties Query", "What are the properties of Inconel 625LCF?", "/public/learn.svg"),
    ("Variants Analysis", "Are there any variants of Inconel 625LCF? Give me properties for each.",
     "/public/write.svg"),
    ("Property Extremes", "Which alloy has the highest tensile strength?", "/public/search.svg"),
]

TEMP_PRESETS = {
    "factual": 0.1,
    "balanced": 0.3,
    "creative": 0.7,
}


# ----- helpers -----
def sanitize_input(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > 2000:
        logger.warning(f"Input too long: {len(text)}")
        return None
    dangerous = ["<script", "javascript:", "onerror=", "eval(", "onclick="]
    if any(d in text.lower() for d in dangerous):
        logger.warning("Potentially dangerous input detected")
        return None
    return text


def detect_mode(q: str) -> str:
    """Match RAG system's classification"""
    ql = (q or "").lower()

    if re.search(r"\b(variant|variants|version|versions|form|forms|condition|conditions)\b", ql):
        return "variants"

    if re.search(r"\b(propert(y|ies)|mechanical|physical|thermal|strength|hardness|modulus|elongation|density)\b", ql):
        if re.search(r"\b(each|every|all)\b", ql):
            return "variants"
        if not re.search(r"\b(highest|maximum|max|lowest|minimum|min|strongest|weakest)\b", ql):
            return "properties"

    if re.search(r"\b(compare|versus|vs\.?|diff(erence)?|between)\b", ql):
        return "compare"
    if re.search(r"\b(highest|maximum|max|best|lowest|minimum|min|worst|strongest|weakest)\b", ql) and \
            re.search(r"\b(tensile|yield|elongation|hardness|elastic|young|modulus|strength|ductility)\b", ql):
        return "extreme_property"

    th_words = ("more than", "over", "above", "at least", "no less than", "less than",
                "below", "under", "no more than", "exceeding", ">=", "<=", ">", "<")
    if any(w in ql for w in th_words) and "%" in ql:
        elem_pattern = r"\b(ni|nickel|cr|chromium|chrome|co|cobalt|fe|iron|mo|molybdenum|" \
                       r"nb|niobium|ti|titanium|al|aluminum|aluminium|w|tungsten|si|silicon|" \
                       r"mn|manganese|cu|copper|ta|tantalum|re|rhenium|b|boron|c|carbon|" \
                       r"p|phosphorus|s|sulfur|sulphur|n|nitrogen|zr|zirconium)\b"
        if re.search(elem_pattern, ql):
            return "filtering"

    if re.search(r"\b(comp|composition|wt%|weight percent|chemical|elements?|alloy content|made of)\b", ql):
        return "composition"

    return "general"


def count_alloys_in_context(ctx: str) -> int:
    n = len(re.findall(r"\bALLOY:\b", ctx))
    if n == 0:
        n = len(re.findall(r"^\s*•\s", ctx, flags=re.MULTILINE))
    return max(n, 1)


def build_enhanced_messages(mode: str, user_q: str, ctx: str, model_name: str, temperature: float):
    """Build mode-specific prompts - updated for properties/variants modes"""

    core_rules = (
        "You are a materials science expert assistant. Your responses MUST be based EXCLUSIVELY on the CONTEXT provided below.\n\n"
        "CRITICAL RULES:\n"
        "1. Use ONLY facts, numbers, and data present in CONTEXT - never invent or estimate\n"
        "2. If information is not in CONTEXT, explicitly state 'This information is not available in the database'\n"
        "3. Preserve all numbers and units EXACTLY as written in CONTEXT\n"
        "4. When multiple variants exist, clearly distinguish them by their full names\n"
        "5. For properties, prefer room temperature (RT/room/ambient) measurements\n"
        "6. Never extrapolate, assume, or generalize beyond what CONTEXT explicitly states\n"
        "7. If CONTEXT says 'No data available', acknowledge this honestly\n"
    )

    if mode == "composition":
        task = (
            "TASK: Report the composition (wt%) and key properties for the alloy(s) the user asked about.\n\n"
            "INSTRUCTIONS:\n"
            "- Start with alloy name and UNS number\n"
            "- List composition elements in order of decreasing content\n"
            "- For each element, provide the exact value/range from CONTEXT\n"
            "- Include key properties if present in CONTEXT\n"
            "- If multiple variants exist, group them clearly\n"
        )
    elif mode == "properties":
        task = (
            "TASK: Report ALL available properties for the requested alloy(s).\n\n"
            "INSTRUCTIONS:\n"
            "- List alloy name and UNS\n"
            "- Show ALL properties present in CONTEXT, grouped by type\n"
            "- For each property, include:\n"
            "  • Value with unit (exactly as in CONTEXT)\n"
            "  • Temperature condition if specified\n"
            "  • Heat treatment if specified\n"
            "- If CONTEXT says 'No property data available', say this clearly\n"
            "- DO NOT list only elements - properties are specific measurements\n"
        )
    elif mode == "variants":
        task = (
            "TASK: Show all variants of the requested alloy with their properties.\n\n"
            "INSTRUCTIONS:\n"
            "- List each variant with its full designation\n"
            "- For each variant show:\n"
            "  • UNS number\n"
            "  • Composition (if different from base)\n"
            "  • ALL available properties with conditions\n"
            "- If a variant has no property data in CONTEXT, say 'No property data available for this variant'\n"
            "- DO NOT invent properties - use only what's in CONTEXT\n"
        )
    elif mode == "filtering":
        task = (
            "TASK: The CONTEXT contains alloys that meet the composition threshold. Report them accurately.\n\n"
            "INSTRUCTIONS:\n"
            "- Start with ONE sentence: 'Found X alloys with [element] [operator] [threshold]%'\n"
            "- List each alloy EXACTLY as shown in CONTEXT\n"
            "- DO NOT change any numbers or add commentary\n"
        )
    elif mode == "extreme_property":
        task = (
            "TASK: Identify the single alloy with the highest/lowest value for the requested property.\n\n"
            "INSTRUCTIONS:\n"
            "- State: 'Alloy with [highest/lowest] [Property]:'\n"
            "- Report: Alloy name (UNS: number) — value unit\n"
            "- Include temperature and heat treatment if specified\n"
        )
    elif mode == "compare":
        task = (
            "TASK: Compare the alloys requested by the user based on CONTEXT data.\n\n"
            "INSTRUCTIONS:\n"
            "- Compare ONLY the alloys mentioned in the user's question\n"
            "- For each alloy provide composition and key properties\n"
            "- Highlight major differences\n"
        )
    else:  # general
        task = (
            "TASK: Answer the user's question using only the information in CONTEXT.\n\n"
            "INSTRUCTIONS:\n"
            "- Provide a clear, factual response\n"
            "- Use bullet points for clarity when appropriate\n"
        )

    system = f"{core_rules}\n{task}\n\nCONTEXT:\n{'=' * 70}\n{ctx}\n{'=' * 70}\n\nIMPORTANT: Your entire response must be derived from CONTEXT. Do not use external knowledge."
    user = f"User Question: {user_q}\n\nProvide your answer based solely on the CONTEXT above."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    options = {
        "temperature": float(temperature),
        "num_predict": 1200,  # Allow longer responses for variant queries
    }
    return messages, options


def add_to_history(question: str, mode: str):
    history = cl.user_session.get("query_history", [])
    history.append({"q": question, "mode": mode})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    cl.user_session.set("query_history", history)


def format_history() -> str:
    history = cl.user_session.get("query_history", [])
    if not history:
        return "No recent queries"
    lines = ["**Recent Queries:**"]
    for i, item in enumerate(reversed(history[-5:]), 1):
        lines.append(f"{i}. {item['q'][:60]}... `[{item['mode']}]`")
    return "\n".join(lines)


# ----- starters -----
@cl.set_starters
async def set_starters():
    return [cl.Starter(label=label, message=msg, icon=icon) for (label, msg, icon) in STARTERS]


# ----- lifecycle -----
@cl.on_chat_start
async def start_chat():
    if RAG_CLASS is None:
        await cl.Message(
            "❌ **Error**: Could not import RAG class.\n\n"
            "Please ensure `SuperalloyRAG` is available."
        ).send()
        return

    cl.user_session.set("model", DEFAULT_MODEL)
    cl.user_session.set("temperature", DEFAULT_TEMPERATURE)
    cl.user_session.set("show_raw_context", False)
    cl.user_session.set("query_history", [])
    cl.user_session.set("rag_instance", None)

    await cl.ChatSettings(
        [
            Select(
                id="model",
                label="🤖 Ollama Model",
                values=["llama3.2", "llama3.1", "mistral"],
                initial_index=0,
            ),
            Select(
                id="temp_preset",
                label="🌡️ Temperature Preset",
                values=["factual", "balanced", "creative"],
                initial_index=0,
            ),
            Slider(
                id="temperature",
                label="🎚️ Temperature (Fine Control)",
                initial=DEFAULT_TEMPERATURE,
                min=0.0,
                max=1.0,
                step=0.05,
            ),
            Switch(
                id="show_raw_context",
                label="🔍 Show Raw Context",
                initial=False,
            ),
        ]
    ).send()

    welcome_msg = (
        "👋 **Welcome to the Nickel-Based Superalloy Assistant**\n\n"
        "I query a knowledge graph of 500+ superalloys and use LLMs to present the data clearly.\n\n"
        "**Try these queries:**\n"
        "• _What is the composition of Inconel 718?_\n"
        "• _What are the properties of Rene Supersolvus?_\n"
        "• _Are there any variants of Inconel 625LCF? Properties for each?_\n"
        "• _Which alloy has the highest tensile strength?_\n\n"
        "**Features:**\n"
        "• Toggle 'Show Raw Context' to see underlying data\n"
        "• Adjust temperature for response style\n"
        "• Type `/clear` to reset | `/history` for recent queries"
    )
    await cl.Message(content=welcome_msg).send()


@cl.on_settings_update
async def on_settings_update(settings):
    if "model" in settings:
        cl.user_session.set("model", settings["model"])
    if "temp_preset" in settings:
        preset = settings["temp_preset"]
        temp = TEMP_PRESETS.get(preset, DEFAULT_TEMPERATURE)
        cl.user_session.set("temperature", temp)
    if "temperature" in settings:
        cl.user_session.set("temperature", float(settings["temperature"]))
    if "show_raw_context" in settings:
        cl.user_session.set("show_raw_context", bool(settings["show_raw_context"]))


@cl.on_message
async def main(message: cl.Message):
    q = sanitize_input(message.content)

    if q and q.lower() == "/clear":
        cl.user_session.set("query_history", [])
        await cl.Message("🔄 **Session cleared.** Ask a new question!").send()
        return

    if q and q.lower() == "/history":
        await cl.Message(format_history()).send()
        return

    if not q:
        await cl.Message(
            "⚠️ **Invalid Input**\n\n"
            "Please enter a valid question (max 2000 characters)."
        ).send()
        return

    mode = detect_mode(q)
    add_to_history(q, mode)

    show_raw = cl.user_session.get("show_raw_context", False)
    model = cl.user_session.get("model", DEFAULT_MODEL)
    temperature = cl.user_session.get("temperature", DEFAULT_TEMPERATURE)

    # Step 1: Query knowledge graph
    context_step = cl.Step(name="🔎 Querying Knowledge Graph", type="retrieval")
    await context_step.send()

    try:
        rag = cl.user_session.get("rag_instance")
        if rag is None:
            rag = RAG_CLASS(q)
            cl.user_session.set("rag_instance", rag)
        else:
            rag.question = q

        ctx = rag.query()
        n_alloys = count_alloys_in_context(ctx)

        context_step.output = f"✅ Retrieved {n_alloys} alloy entries | Mode: `{mode}`"
        await context_step.update()

        # Show raw context if enabled
        if show_raw and ctx:
            raw_msg = cl.Message(
                content=f"**Raw Context from Knowledge Graph:**\n```\n{ctx[:3000]}{'...' if len(ctx) > 3000 else ''}\n```",
                author="System"
            )
            await raw_msg.send()

    except Exception as e:
        logger.exception("RAG query failed")
        context_step.output = f"❌ Error: {str(e)}"
        await context_step.update()

        await cl.Message(
            f"❌ **Retrieval Error**\n\n"
            f"Failed to query the knowledge graph: `{str(e)}`\n\n"
            f"This may be due to:\n"
            f"• Weaviate connection issues\n"
            f"• Invalid query format\n"
            f"• Database unavailable"
        ).send()
        return

    # Check for meaningful context
    if not ctx or ctx.startswith("No matching") or ctx.startswith("Invalid query"):
        await cl.Message(
            f"ℹ️ **No Results Found**\n\n"
            f"{ctx}\n\n"
            f"Try:\n"
            f"• Checking alloy name spelling\n"
            f"• Using common designations (e.g., 'Inconel 718')\n"
            f"• Broadening your search criteria"
        ).send()
        return

    # Check if database has property data
    if "No property data available" in ctx or "No data available" in ctx:
        # Still send to LLM but with special handling
        await cl.Message(
            "⚠️ **Note**: The database may have limited or no property data for this alloy. "
            "I'll show what's available."
        ).send()

    # Step 2: Generate natural language response
    llm_step = cl.Step(name="🤖 Generating Response", type="llm")
    await llm_step.send()

    try:
        messages, options = build_enhanced_messages(mode, q, ctx, model, temperature)

        llm_step.output = f"Model: {model} | Temp: {temperature}"
        await llm_step.update()

        # Stream response
        stream = ollama.chat(model=model, messages=messages, stream=True, options=options)
        out = cl.Message(content="")

        for chunk in stream:
            token = chunk.get("message", {}).get("content", "")
            if token:
                await out.stream_token(token)

        await out.send()

    except ollama.ResponseError as e:
        logger.exception("Ollama ResponseError")
        llm_step.output = f"❌ LLM Error: {str(e)}"
        await llm_step.update()

        await cl.Message(
            f"⚠️ **LLM Processing Failed**\n\n"
            f"Showing raw database results:\n\n"
            f"---\n\n{ctx[:2000]}{'...' if len(ctx) > 2000 else ''}"
        ).send()

    except Exception as e:
        logger.exception("Unexpected error during LLM processing")
        llm_step.output = f"❌ Error: {str(e)}"
        await llm_step.update()

        await cl.Message(
            f"⚠️ **Error Processing Response**\n\n"
            f"Falling back to database results:\n\n"
            f"---\n\n{ctx[:2000]}{'...' if len(ctx) > 2000 else ''}"
        ).send()


@cl.on_chat_end
async def end_chat():
    rag = cl.user_session.get("rag_instance")
    if rag:
        try:
            pass
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")


if __name__ == "__main__":
    from chainlit.cli import run_chainlit

    run_chainlit(__file__)