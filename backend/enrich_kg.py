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
REPO_ID = os.getenv("GRAPHDB_REPO", "NiSuperAlloy_json")
JSON_FILE = os.getenv("ALLOY_JSON", "/Users/alexlecu/PycharmProjects/AlloyMind/backend/scrape/Data/processed_materials.jsonl")
NAMED_GRAPH = URIRef("http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy")

BASE = "http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy#"
NS = Namespace(BASE)

PROPERTY_MAP: Dict[str, str] = {
    "tensile_strength_mpa": "TensileStrength",
    "yield_strength_mpa": "YieldStrength",
    "elongation_pct": "Elongation",
    "hardness_rockwell": "Hardness",
    "elastic_modulus_gpa": "ElasticModulus",
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
            if line.strip():
                alloys.append(json.loads(line))

    elements_seen = set()

    for alloy_data in alloys:
        alloy_name = alloy_data.get("alloy", "")
        uns = alloy_data.get("uns", "")

        a_uri = mint_stable("Alloy", alloy_name)
        g.add((a_uri, RDF.type, NS.NickelBasedSuperalloy))
        g.add((a_uri, RDFS.label, Literal(alloy_name)))
        g.add((a_uri, NS.tradeDesignation, Literal(alloy_name)))
        if uns:
            g.add((a_uri, NS.unsNumber, Literal(uns)))

        c_uri = mint_stable("Comp", alloy_name)
        g.add((c_uri, RDF.type, NS.Composition))
        g.add((a_uri, NS.hasComposition, c_uri))

        composition = alloy_data.get("composition", {})
        for elem_symbol, elem_data in composition.items():
            if elem_symbol not in elements_seen:
                e_uri = mint_stable("Element", elem_symbol)
                g.add((e_uri, RDF.type, NS.Element))
                g.add((e_uri, RDFS.label, Literal(elem_symbol)))
                elements_seen.add(elem_symbol)

            add_comp_entry(g, c_uri, mint_stable("Element", elem_symbol), elem_data)

        for variant in alloy_data.get("variants", []):
            variant_alias = variant.get("alias", "")
            processing = variant.get("processing", "")
            source_url = variant.get("source_url", "")

            if not variant_alias:
                log.warning(f"Skipping variant without alias for alloy {alloy_name}")
                continue

            v_uri = mint_stable("Variant", variant_alias)
            g.add((v_uri, RDF.type, NS.Variant))
            g.add((v_uri, RDFS.label, Literal(variant_alias)))
            g.add((a_uri, NS.hasVariant, v_uri))

            g.add((v_uri, NS.variantName, Literal(variant_alias)))
            if processing:
                g.add((v_uri, NS.processingMethod, Literal(processing)))
            if source_url:
                g.add((v_uri, NS.sourceUrl, Literal(source_url)))

            properties = variant.get("properties", {})

            for prop_key, prop_class in PROPERTY_MAP.items():
                measurements = properties.get(prop_key, [])

                if not measurements:
                    continue

                propset_uri = mint_stable("PropSet", f"{variant_alias}_{prop_class}")
                g.add((propset_uri, RDF.type, NS.PropertySet))
                g.add((v_uri, NS.hasPropertySet, propset_uri))
                g.add((propset_uri, NS.measuresProperty, URIRef(BASE + prop_class)))

                for meas_data in measurements:
                    meas = mint("Meas", f"{variant_alias}_{prop_class}")
                    g.add((meas, RDF.type, NS.Measurement))
                    g.add((propset_uri, NS.hasMeasurement, meas))

                    temp_c = meas_data.get("temp_c")
                    temp_category = meas_data.get("temp_category")
                    if temp_category:
                        g.add((meas, NS.temperatureCategory, Literal(temp_category)))
                    if temp_c is not None:
                        temp_qty = add_quantity(g, "°C", {"value": temp_c})
                        g.add((meas, NS.hasTestTemperature, temp_qty))

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

    resp = requests.post(endpoint, params=params, data=ttl_bytes, headers=headers, timeout=120)
    if resp.status_code // 100 != 2:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    log.info("✅ Uploaded to %s (repo %s)", NAMED_GRAPH, REPO_ID)


def main():
    if not Path(JSON_FILE).exists():
        raise SystemExit(f"Missing JSON file: {JSON_FILE}")
    g = build_graph(JSON_FILE)
    upload_graph(g)


if __name__ == "__main__":
    main()