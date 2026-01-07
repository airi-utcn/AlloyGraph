import os
import json
from dataclasses import asdict
from difflib import SequenceMatcher
from groq import Groq
from .alloy_retriever import AlloyRetriever
from .config import LLMConfig, SearchConfig, HistoryConfig, Prompts

# In-memory session storage (can be externalized later)
chat_sessions = {}

def _format_history(history: list, depth: int, max_content: int = 100) -> str:
    """Format conversation history for LLM context."""
    hist_str = ""
    for msg in reversed(history[-depth:]):
        role = msg.get('role', '')
        content = msg.get('content', '')[:max_content]
        if role in ['user', 'assistant']:
            hist_str = f"{role}: {content}\n" + hist_str
    return hist_str

def find_best_match(target_name: str, search_results: list):
    """
    Find the best matching alloy from search results based on similarity.
    Returns the best match if above threshold, None otherwise.
    """
    if not search_results:
        return None
    
    scored = []
    for alloy in search_results:
        # Clean names for better matching (remove asterisks and normalize)
        clean_alloy_name = alloy.name.lower().replace('*', '').strip()
        clean_target = target_name.lower().strip()
        
        # Calculate similarity
        ratio = SequenceMatcher(None, clean_target, clean_alloy_name).ratio()
        
        # Boost score if target is substring of alloy name
        if clean_target in clean_alloy_name:
            ratio += SearchConfig.SUBSTRING_MATCH_BOOST
        
        scored.append((ratio, alloy))
    
    # Sort by score and take best
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_alloy = scored[0]
    
    # Return only if above minimum threshold
    if best_score >= SearchConfig.MIN_SIMILARITY_THRESHOLD:
        return best_alloy
    
    return None

def detect_query_intent(prompt: str, history: list) -> dict:
    """Classify the user query intent using LLM."""
    try:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            return {"intent": "SEARCH"}

        client = Groq(api_key=groq_key)
        
        hist_str = _format_history(history, HistoryConfig.EXTRACTION_CONTEXT_DEPTH, max_content=100)

        completion = client.chat.completions.create(
            model=LLMConfig.MODEL,
            messages=[
                {"role": "system", "content": Prompts.INTENT_CLASSIFICATION},
                {"role": "user", "content": f"History:\n{hist_str}\nQuery: {prompt}"}
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ Error in intent detection: {e}")
        return {"intent": "SEARCH"}

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
        
        hist_str = _format_history(history, HistoryConfig.EXTRACTION_CONTEXT_DEPTH, max_content=200)

        system_instruction = Prompts.ALLOY_EXTRACTION

        completion = client.chat.completions.create(
            model=LLMConfig.MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"History:\n{hist_str}\nCurrent Query: {prompt}"}
            ],
            temperature=LLMConfig.EXTRACTION_TEMPERATURE,
            max_tokens=LLMConfig.EXTRACTION_MAX_TOKENS
        )
        
        result = completion.choices[0].message.content.strip()
        if "None" in result or not result:
            return ""
        return result
    except Exception as e:
        print(f"⚠️ Error in alloy extraction: {e}")
        return ""

def process_analytics_query(params: dict, retriever: AlloyRetriever):
    """
    Handle analytical queries by fetching candidates and sorting in Python.
    """
    prop_target = params.get('property', '').lower()
    direction = params.get('direction', 'highest')
    limit = params.get('limit', 5)
    
    # Map common terms to search keywords
    search_term = prop_target
    if "strength" in prop_target: search_term = "strength"
    if "yield" in prop_target: search_term = "yield"
    if "tensile" in prop_target or "uts" in prop_target: search_term = "tensile"
    if "elongation" in prop_target: search_term = "elongation"
    if "density" in prop_target: search_term = "density"
    
    candidates = retriever.get_alloys_with_property(search_term, limit=100)
    
    # Extract values for sorting
    scored = []
    for alloy in candidates:
        # Find best value for this property
        best_val = -1.0 if direction == 'highest' else float('inf')
        found = False
        selected_prop = None
        
        # density check
        if "density" in search_term and alloy.density_gcm3:
            best_val = alloy.density_gcm3
            found = True
            selected_prop = f"{best_val} g/cm³"
        else:
            # properties check
            if alloy.properties:
                for p in alloy.properties:
                    p_type = p.property_type.lower()
                    # Simple matching
                    is_match = False
                    if "yield" in search_term and ("yield" in p_type or "0.2%" in p_type): is_match = True
                    elif "tensile" in search_term and ("ultimate" in p_type or "tensile" in p_type or "uts" in p_type): is_match = True
                    elif "elongation" in search_term and "elongation" in p_type: is_match = True
                    elif search_term in p_type: is_match = True
                    
                    if is_match and p.value is not None:
                        val = p.value
                        temp = p.temperature_c if p.temperature_c is not None else -1
                        is_room = 20 <= temp <= 25
                        
                        if not found:
                            best_val = val
                            selected_prop = p
                            found = True
                        else:
                            # Prefer room temp for general queries
                            existing_temp = selected_prop.temperature_c if isinstance(selected_prop, object) and hasattr(selected_prop, 'temperature_c') and selected_prop.temperature_c else -1
                            existing_is_room = 20 <= existing_temp <= 25
                            
                            if is_room and not existing_is_room:
                                best_val = val
                                selected_prop = p
                                
        if found:
            scored.append({
                "alloy": alloy,
                "value": best_val,
                "display": selected_prop
            })
            
    # Sort
    reverse = (direction == 'highest')
    scored.sort(key=lambda x: x['value'], reverse=reverse)
    
    return [item['alloy'] for item in scored[:limit]]

def stream_chat_response(prompt: str, session_id: str, history: list):
    """
    Generator function that streams both alloy data and LLM response.
    """
    with AlloyRetriever() as retriever:
        intent_data = detect_query_intent(prompt, history)
        intent = intent_data.get("intent", "SEARCH")
        
        target_alloys = []
        final_context = ""
        
        if intent == "ANALYTICS":
            # Analytical Path
            print(f"📊 Analytics Query: {intent_data}")
            target_alloys = process_analytics_query(intent_data.get("params", {}), retriever)
            final_context = f"Top results for {intent_data.get('params', {}).get('property')} ({intent_data.get('params', {}).get('direction')}):\n"
            final_context += retriever.format_for_llm(target_alloys)
            
        elif intent == "DESIGN":
            # Design Path
            final_context = "User wants to design an alloy. Encourage them to use the Designer tool."
            
        else:
            # Standard Search Path
            target_names_str = get_target_alloy_from_llm(prompt, history)
            
            if not target_names_str:
                 raw_results = retriever.search_alloys(prompt, limit=5)
                 # Strict Filter for generic search
                 for alloy in raw_results:
                     ratio = SequenceMatcher(None, prompt.lower(), alloy.name.lower()).ratio()
                     if ratio >= SearchConfig.MIN_SIMILARITY_THRESHOLD:
                         target_alloys.append(alloy)
            else:
                 targets = [t.strip() for t in target_names_str.split(',') if t.strip()]
                 target_alloys = []
                 
                 for t in targets:
                    matches = retriever.search_alloys(t, limit=5)
                    best = find_best_match(t, matches)
                    if best:
                        if not any(a.name == best.name for a in target_alloys):
                            target_alloys.append(best)
                 
                 # Comparison Safety Net
                 if len(target_alloys) < 2 and len(targets) > 1:
                     extra = retriever.search_alloys(prompt, limit=5)
                     for ex in extra:
                         if not any(a.name == ex.name for a in target_alloys):
                             # Apply strict filter here too
                             ratio = SequenceMatcher(None, prompt.lower(), ex.name.lower()).ratio()
                             if ratio >= SearchConfig.MIN_SIMILARITY_THRESHOLD:
                                target_alloys.append(ex)

            final_context = retriever.format_for_llm(target_alloys)

        # Send Alloy Data Chunk
        serialized_alloys = [asdict(a) for a in target_alloys] if target_alloys else []
        yield json.dumps({"type": "data", "alloys": serialized_alloys}) + "\n"
        
        if intent == "DESIGN":
             yield json.dumps({"type": "tool_suggestion", "tool": "designer"}) + "\n"
        
        if not target_alloys and intent != "DESIGN":
             yield json.dumps({"type": "chunk", "content": "No matching alloys found in the knowledge graph."}) + "\n"
             return

        # Stream LLM Response
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            client = Groq(api_key=groq_key)
            
            system_prompt = Prompts.CHAT_RESPONSE
            if intent == "ANALYTICS":
                system_prompt = Prompts.ANALYTICS_RESPONSE
            
            messages = [{"role": "system", "content": system_prompt}]
            for msg in history[-HistoryConfig.MAX_CONTEXT_MESSAGES:]:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
            
            user_message = f"Context:\n{final_context}\n\nUser Query: {prompt}"
            messages.append({"role": "user", "content": user_message})

            stream = client.chat.completions.create(
                model=LLMConfig.MODEL,
                messages=messages,
                max_tokens=LLMConfig.RESPONSE_MAX_TOKENS,
                temperature=LLMConfig.RESPONSE_TEMPERATURE,
                stream=True
            )

            full_response = ""
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    yield json.dumps({"type": "chunk", "content": content}) + "\n"
            
            # Save to history
            if session_id not in chat_sessions:
                chat_sessions[session_id] = []
            
            chat_sessions[session_id].append({
                "prompt": prompt,
                "response": full_response,
                "alloys": [a.name for a in target_alloys]
            })
