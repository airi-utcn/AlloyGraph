from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json

from alloy_crew.alloy_evaluator import AlloyEvaluationCrew
from alloy_crew.alloy_designer import IterativeDesignCrew
from alloy_retriever import AlloyRetriever
from groq import Groq

app = Flask(__name__)
CORS(app)

DEFAULT_LLM = "groq/llama-3.3-70b-versatile"

# In-memory session storage
chat_sessions = {}

def get_target_alloy_from_llm(prompt: str, history: list) -> str:
    """
    Use LLM to identify which alloy is the subject of the user's query.
    Handles context switches and implicit references ('it', 'the alloy').
    """
    try:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return ""

        client = Groq(api_key=groq_key)
        
        # Format history string
        hist_str = ""
        for msg in reversed(history[-4:]): # Last 2 exchanges
            role = msg.get('role')
            content = msg.get('content', '')[:200] # Truncate for brevity
            if role in ['user', 'assistant']:
                hist_str = f"{role}: {content}\n" + hist_str

        system_instruction = (
            "You are a query analyzer. Identify the specific ALLOY name the user is asking about right now. "
            "Rules:\n"
            "1. If user mentions a new alloy (e.g., 'What about Waspaloy?'), return THAT name.\n"
            "2. If user says 'it' or asks a follow-up (e.g., 'What's the density?'), return the Alloy Name from previous messages.\n"
            "3. Return ONLY the alloy name (e.g., 'Inconel 718', 'Waspaloy').\n"
            "4. If no alloy is involved, return 'None'."
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"History:\n{hist_str}\nUser Current Query: {prompt}"}
            ],
            temperature=0.0,
            max_tokens=20
        )
        
        result = completion.choices[0].message.content.strip()
        if "None" in result or len(result) > 50: # Safety check
            return ""
            
        # Cleanup punctuation
        return result.strip(".\"'")
        
    except Exception as e:
        print(f"Error in LLM alloy detection: {e}")
        return ""


@app.route('/health', methods=['GET'])
def health_check():
    return {"status": "ok", "message": "Backend is running"}, 200  # Enable CORS for frontend


@app.route('/api/validate', methods=['POST'])
def validate_alloy():
    """Run the Validator Agent on a composition."""
    data = request.json
    composition = data.get('composition')
    temp = data.get('temp', 20)
    processing = data.get('processing', 'cast')
    llm = data.get('llm', DEFAULT_LLM)

    if not composition:
        return jsonify({"error": "No composition provided"}), 400

    print(f"🔹 Validating: {composition} @ {temp}°C ({processing})")
    
    try:
        crew = AlloyEvaluationCrew(llm_config=llm)
        result = crew.run(composition=composition, processing=processing, temperature=temp)
        
        return jsonify({"result": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/design', methods=['POST'])
def design():
    """Design alloy based on target properties"""
    data = request.json
    
    # Extract target_props as a dict
    target_props = data.get('target_props', {})
    
    # Fallback to individual params for backward compatibility
    if not target_props:
        target_props = {'Yield Strength': data.get('yield_strength', 1000)}
        if data.get('tensile_strength', 0) > 0:
            target_props['Tensile Strength'] = data.get('tensile_strength')
        if data.get('elongation', 0) > 0:
            target_props['Elongation'] = data.get('elongation')
        if data.get('density', 99) < 99:
            target_props['Density'] = data.get('density')
        if data.get('gamma_prime', 0) > 0:
            target_props['Gamma Prime'] = data.get('gamma_prime')
    
    processing = data.get('processing', 'cast')
    temperature = data.get('temp', 900)
    max_iter = data.get('max_iter', 3)

    print(f"\n🎨 DESIGN REQUEST:")
    print(f"   Targets: {target_props}")
    print(f"   Processing: {processing}, Temp: {temperature}°C, Max Iterations: {max_iter}")

    try:
        crew = IterativeDesignCrew(target_props)
        result = crew.loop(max_iterations=max_iter, processing=processing, temperature=temperature)
        return jsonify({"result": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



@app.route('/api/chat', methods=['POST'])
def chat_kg():
    """Advanced RAG chat with Knowledge Graph using Groq LLM and conversation history."""
    data = request.json
    prompt = data.get('prompt')
    session_id = data.get('sessionId', 'default')
    history = data.get('history', [])  # List of {role, content} messages

    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    print(f"🔹 Chat [{session_id}]: {prompt}")

    try:
        # Use LLM to smartly determine the target alloy context
        target_alloy = get_target_alloy_from_llm(prompt, history)
        
        print(f"🎯 Identified Target Alloy: '{target_alloy}'")
        
        # If we identified an alloy, make sure it's in the search query
        if target_alloy and target_alloy.lower() not in prompt.lower():
             search_query = f"{target_alloy} {prompt}"
        else:
             search_query = prompt
        
        with AlloyRetriever() as kg:
            alloys = kg.search_alloys(search_query, limit=5)
            raw_answer = kg.format_for_llm(alloys)
        
        if not alloys:
            return jsonify({"result": "No matching alloys found in the knowledge graph for your query."})
        
        # Post-process with Groq for intelligent, context-aware answers
        try:
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                groq_client = Groq(api_key=groq_key)
                
                system_prompt = (
                    "You are a materials science expert helping a user explore alloy data. "
                    "The conversation history shows what they've asked before. "
                    "Use this context to understand follow-up questions and references like 'it', 'the alloy', or 'them'. "
                    "You have access to detailed technical data from our database with temperature-specific measurements. "
                    "Answer the user's SPECIFIC question based on this data. "
                    "Be concise, accurate, and directly address what they asked for. "
                    "If they asked for specific conditions (e.g., 'room temperature', 'at 700°C'), "
                    "filter the data to show only relevant measurements. Note: room temperature is typically 20-25°C."
                )
                
                # Build conversation messages for Groq
                messages = [{"role": "system", "content": system_prompt}]
                
                # Add conversation history (last 10 messages for context)
                for msg in history[-10:]:
                    messages.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")
                    })
                
                # Add current query with database results
                user_message = (
                    f"User Question: {prompt}\n\n"
                    f"Database Results:\n{raw_answer}\n\n"
                    f"Please provide a clear, direct answer to their question."
                )
                messages.append({"role": "user", "content": user_message})
                
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.2,
                    max_tokens=800
                )
                
                refined_answer = response.choices[0].message.content.strip()
                if refined_answer:
                    # Add metadata tag so the history tracker (and LLM) knows what we talked about
                    if target_alloy:
                        final_answer = f"[Queried alloys: {target_alloy}]\n\n{refined_answer}"
                    else:
                        final_answer = refined_answer
                    
                    if session_id not in chat_sessions:
                        chat_sessions[session_id] = []
                    chat_sessions[session_id].append({
                        "prompt": prompt,
                        "response": final_answer,
                        "alloys": [a.name for a in alloys]
                    })
                    
                    return jsonify({"result": final_answer})
        except Exception as e:
            print(f"Groq post-processing failed: {e}")
        
        # Fallback to raw answer
        return jsonify({"result": raw_answer})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
