import os
import uuid
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD
import requests

GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://localhost:7200")
REPO_ID = os.getenv("GRAPHDB_REPO", "NiSuperAlloy")
JSON_FILE = os.getenv("ALLOY_JSON", "/Users/alexlecu/PycharmProjects/AlloyMind/backend/scrape/Data_Grok/data_clean_deduplicated_20251120.jsonl")
NAMED_GRAPH = URIRef("http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy")

BASE = "http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy#"
NS = Namespace(BASE)

PROPERTY_MAP: Dict[str, str] = {
    "tensile_strength_mpa": "TensileStrength",
    "yield_strength_mpa": "YieldStrength",
    "elongation_pct": "Elongation",
    "hardness": "Hardness",
    "elastic_modulus_gpa": "ElasticModulus",
    "creep_rupture_hours": "CreepRupture",
    "reduction_of_area_pct": "ReductionOfArea",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("json->graphdb")


def iri_local(s: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "_+.-" else "_" for ch in s)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def mint(prefix: str, hint: str) -> URIRef:
    return URIRef(BASE + f"{prefix}_{iri_local(hint)}_{uuid.uuid4().hex[:8]}")


def mint_stable(prefix: str, hint: str) -> URIRef:
    return URIRef(BASE + f"{prefix}_{iri_local(hint)}")


def add_quantity(g: Graph, unit: Optional[str], data: Dict[str, Any]) -> URIRef:
    q = mint("Qty", unit or "qty")
    g.add((q, RDF.type, NS.Quantity))
    if unit:
        g.add((q, NS.unitSymbol, Literal(unit)))

    min_v = data.get("min")
    max_v = data.get("max")
    if (min_v is not None) and (max_v is not None) and (float(min_v) > float(max_v)):
        min_v, max_v = float(max_v), float(min_v)

    if data.get("value") is not None:
        g.add((q, NS.numericValue, Literal(float(data["value"]), datatype=XSD.decimal)))
    if min_v is not None:
        g.add((q, NS.minInclusive, Literal(float(min_v), datatype=XSD.decimal)))
    if max_v is not None:
        g.add((q, NS.maxInclusive, Literal(float(max_v), datatype=XSD.decimal)))
    if data.get("approx"):
        g.add((q, NS.isApproximate, Literal(True, datatype=XSD.boolean)))
    if data.get("qualifier"):
        g.add((q, NS.qualifier, Literal(data["qualifier"])))
    if data.get("raw"):
        g.add((q, NS.rawString, Literal(data["raw"])))

    return q


def add_comp_entry(g: Graph, comp_uri: URIRef, elem_uri: URIRef, data: Dict[str, Any]):
    entry = mint("Entry", f"{Path(str(elem_uri)).name}")
    g.add((entry, RDF.type, NS.CompositionEntry))
    g.add((comp_uri, NS.hasComponent, entry))
    g.add((entry, NS.element, elem_uri))
    
    if isinstance(data, (int, float)):
        data = {"value": data}
        
    if data.get("is_balance_remainder"):
        g.add((entry, NS.isBalanceRemainder, Literal(True, datatype=XSD.boolean)))
    else:
        q_data = {}
        if data.get("value") is not None:
            q_data["value"] = data["value"]
        if data.get("min") is not None:
            q_data["min"] = data["min"]
        if data.get("max") is not None:
            q_data["max"] = data["max"]
        if data.get("qualifier"):
            q_data["qualifier"] = data["qualifier"]
        if data.get("raw"):
            q_data["raw"] = data["raw"]
        if data.get("approx"):
            q_data["approx"] = data["approx"]

        if q_data:
            q_uri = add_quantity(g, data.get("unit", "%"), q_data)
            g.add((entry, NS.hasMassFraction, q_uri))


def build_graph(json_path: str) -> Graph:
    log.info("Reading JSON: %s", json_path)

    g = Graph()
    g.bind("ns", NS);
    g.bind("rdf", RDF);
    g.bind("rdfs", RDFS);
    g.bind("xsd", XSD)

    alloys = []
    with open(json_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip() and not line.startswith("==>"):
                try:
                    alloys.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning(f"Skipping invalid JSON line: {line[:50]}...")

    elements_seen = set()

    for alloy_data in alloys:
        alloy_name = alloy_data.get("alloy", "")
        if not alloy_name: continue

        uns = alloy_data.get("uns", "")

        a_uri = mint_stable("Alloy", alloy_name)
        g.add((a_uri, RDF.type, NS.NickelBasedSuperalloy))
        g.add((a_uri, RDFS.label, Literal(alloy_name)))
        g.add((a_uri, NS.tradeDesignation, Literal(alloy_name)))
        if uns:
            g.add((a_uri, NS.unsNumber, Literal(uns)))
            
        if alloy_data.get("family"):
            g.add((a_uri, NS.family, Literal(alloy_data["family"])))
        if alloy_data.get("density_gcm3"):
            g.add((a_uri, NS.density, Literal(float(alloy_data["density_gcm3"]), datatype=XSD.decimal)))
        if alloy_data.get("gamma_prime_vol_pct") is not None:
            g.add((a_uri, NS.gammaPrimeVolPct, Literal(float(alloy_data["gamma_prime_vol_pct"]), datatype=XSD.decimal)))
        if alloy_data.get("typical_heat_treatment"):
            g.add((a_uri, NS.typicalHeatTreatment, Literal(alloy_data["typical_heat_treatment"])))

        c_uri = mint_stable("Comp", alloy_name)
        g.add((c_uri, RDF.type, NS.Composition))
        g.add((a_uri, NS.hasComposition, c_uri))

        composition = alloy_data.get("composition", {})
        for elem_symbol, elem_data in composition.items():
            if elem_symbol == "other": continue
            
            if elem_symbol not in elements_seen:
                e_uri = mint_stable("Element", elem_symbol)
                g.add((e_uri, RDF.type, NS.Element))
                g.add((e_uri, RDFS.label, Literal(elem_symbol)))
                elements_seen.add(elem_symbol)

            add_comp_entry(g, c_uri, mint_stable("Element", elem_symbol), elem_data)

        for variant in alloy_data.get("variants", []):
            variant_name = variant.get("variant_name", "")
            processing = variant.get("processing", "")
            source = variant.get("source", "")

            if not variant_name:
                log.warning(f"Skipping variant without name for alloy {alloy_name}")
                continue

            v_uri = mint_stable("Variant", f"{alloy_name}_{variant_name}")
            g.add((v_uri, RDF.type, NS.Variant))
            g.add((v_uri, RDFS.label, Literal(variant_name)))
            g.add((a_uri, NS.hasVariant, v_uri))

            g.add((v_uri, NS.variantName, Literal(variant_name)))
            if processing:
                g.add((v_uri, NS.processingMethod, Literal(processing)))
            if source:
                g.add((v_uri, NS.sourceUrl, Literal(source)))

            # Handle mechanical properties structure
            mech_props = variant.get("mechanical_properties", {})
            # Also check for old 'properties' key just in case
            if not mech_props and "properties" in variant:
                mech_props = variant["properties"]

            for prop_key, prop_class in PROPERTY_MAP.items():
                measurements = mech_props.get(prop_key, [])

                if not measurements:
                    continue

                propset_uri = mint_stable("PropSet", f"{alloy_name}_{variant_name}_{prop_class}")
                g.add((propset_uri, RDF.type, NS.PropertySet))
                g.add((v_uri, NS.hasPropertySet, propset_uri))
                g.add((propset_uri, NS.measuresProperty, URIRef(BASE + prop_class)))

                for meas_data in measurements:
                    meas = mint("Meas", f"{alloy_name}_{variant_name}_{prop_class}")
                    g.add((meas, RDF.type, NS.Measurement))
                    g.add((propset_uri, NS.hasMeasurement, meas))

                    temp_c = meas_data.get("temp_c")
                    temp_category = meas_data.get("temp_category")
                    if temp_category:
                        g.add((meas, NS.temperatureCategory, Literal(temp_category)))
                    if temp_c is not None:
                        temp_qty = add_quantity(g, "°C", {"value": temp_c})
                        g.add((meas, NS.hasTestTemperature, temp_qty))
                        
                    if "stress_mpa" in meas_data:
                        g.add((meas, NS.stress, Literal(float(meas_data["stress_mpa"]), datatype=XSD.decimal)))
                    if "life_hours" in meas_data:
                        g.add((meas, NS.lifeHours, Literal(float(meas_data["life_hours"]), datatype=XSD.decimal)))

                    q_data = {}
                    if meas_data.get("value") is not None:
                        q_data["value"] = meas_data["value"]
                    if meas_data.get("min") is not None:
                        q_data["min"] = meas_data["min"]
                    if meas_data.get("max") is not None:
                        q_data["max"] = meas_data["max"]
                    if meas_data.get("qualifier"):
                        q_data["qualifier"] = meas_data["qualifier"]
                    if meas_data.get("raw"):
                        q_data["raw"] = meas_data["raw"]
                    if meas_data.get("approx"):
                        q_data["approx"] = meas_data["approx"]

                    unit = meas_data.get("unit", "")
                    if not unit:
                        if "_mpa" in prop_key: unit = "MPa"
                        elif "_pct" in prop_key: unit = "%"
                        elif "_gpa" in prop_key: unit = "GPa"
                        elif prop_key == "hardness" and "scale" in meas_data:
                            unit = meas_data["scale"]

                    q_uri = add_quantity(g, unit, q_data)
                    g.add((meas, NS.hasQuantity, q_uri))

    log.info("Graph built with %d triples", len(g))
    return g


def upload_graph(g: Graph):
    ttl_bytes = g.serialize(format="turtle").encode("utf-8")
    log.info("Uploading %d triples directly to GraphDB…", len(g))

    endpoint = f"{GRAPHDB_URL}/repositories/{REPO_ID}/statements"
    params = {"context": f"<{NAMED_GRAPH}>"}
    headers = {"Content-Type": "text/turtle; charset=UTF-8"}

    # Clear graph first to prevent duplication
    log.info("Clearing graph %s...", NAMED_GRAPH)
    del_endpoint = f"{GRAPHDB_URL}/repositories/{REPO_ID}/statements"
    del_params = {"context": f"<{NAMED_GRAPH}>"}
    requests.delete(del_endpoint, params=del_params)

    resp = requests.post(endpoint, params=params, data=ttl_bytes, headers=headers, timeout=120)
    if resp.status_code // 100 != 2:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    log.info("✅ Uploaded to %s (repo %s)", NAMED_GRAPH, REPO_ID)


ONTOLOGY_FILE = os.getenv("ONTOLOGY_FILE", "../Data/Ontology/NiSuperAlloy_Ont_GEN.rdf")

def create_repo_if_missing():
    """Checks if the repository exists, and if not, creates it."""
    # Check if repo exists
    resp = requests.get(f"{GRAPHDB_URL}/repositories/{REPO_ID}", headers={"Accept": "application/json"})
    if resp.status_code == 200:
        log.info(f"Repository '{REPO_ID}' already exists.")
        return
    elif resp.status_code != 404:
        log.warning(f"Unexpected status code checking for repo: {resp.status_code}. Assuming it doesn't exist.")
    
    log.info(f"Repository '{REPO_ID}' not found. Creating it...")
    
    # Repository Configuration
    repo_config_path = Path(__file__).parent / "repo-config.ttl"
    if not repo_config_path.exists():
         raise RuntimeError(f"Repository config file not found: {repo_config_path}")

    with open(repo_config_path, "r") as f:
        repo_config_template = f.read()
    
    # Replace placeholder if needed, or ensure ID matches. 
    # Since we hardcoded "NiSuperAlloy" in the ttl file, we can just use it.
    # If REPO_ID is dynamic, we should replace it.
    repo_config = repo_config_template.replace('repositoryID> "NiSuperAlloy"', f'repositoryID> "{REPO_ID}"')

    # Prepare multipart/form-data request
    files = {
        'config': ('config.ttl', repo_config, 'text/turtle')
    }
    
    create_resp = requests.post(f"{GRAPHDB_URL}/rest/repositories", files=files)
    
    if create_resp.status_code // 100 != 2:
        # If it failed because it already exists (race condition or check failure), just log it
        if create_resp.status_code == 400 and "already exists" in create_resp.text:
             log.info(f"Repository '{REPO_ID}' already exists (caught 400).")
             return
        raise RuntimeError(f"Failed to create repository: {create_resp.status_code} {create_resp.text}")
        
    log.info(f"✅ Repository '{REPO_ID}' created successfully.")


def upload_ontology():
    if not Path(ONTOLOGY_FILE).exists():
        log.warning(f"Ontology file not found: {ONTOLOGY_FILE}. Skipping ontology upload.")
        return

    log.info(f"Reading Ontology: {ONTOLOGY_FILE}")
    with open(ONTOLOGY_FILE, "rb") as f:
        rdf_data = f.read()

    log.info(f"Uploading Ontology ({len(rdf_data)} bytes) to GraphDB...")
    endpoint = f"{GRAPHDB_URL}/repositories/{REPO_ID}/statements"
    params = {"context": f"<{NAMED_GRAPH}>"}
    headers = {"Content-Type": "application/rdf+xml; charset=UTF-8"}

    resp = requests.post(endpoint, params=params, data=rdf_data, headers=headers, timeout=120)
    if resp.status_code // 100 != 2:
        raise RuntimeError(f"Ontology upload failed: {resp.status_code} {resp.text}")
    log.info("✅ Ontology uploaded successfully")


def main():
    # Ensure Repo Exists
    create_repo_if_missing()

    # Upload Ontology first
    upload_ontology()

    if not Path(JSON_FILE).exists():
        raise SystemExit(f"Missing JSON file: {JSON_FILE}")
    g = build_graph(JSON_FILE)
    upload_graph(g)


if __name__ == "__main__":
    main()