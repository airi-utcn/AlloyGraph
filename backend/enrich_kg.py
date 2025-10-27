import os
import re
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple, Any

import pandas as pd
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD
import requests

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://localhost:7200")
REPO_ID     = os.getenv("GRAPHDB_REPO", "NiSuperAlloys")
XLSX_FILE   = os.getenv("ALLOY_XLSX",  "../Data/NiSuperAlloyProperties.xlsx")
NAMED_GRAPH = URIRef("http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy")

BASE = "http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy#"
NS   = Namespace(BASE)

SHEET_COMPOSITION = "Chemical Properties"
SHEET_MECHANICAL  = "Mechanical Properties"

PROPERTY_MAP: Dict[str, Tuple[str, Optional[str]]] = {
    "Tensile Strength (MPa)": ("TensileStrength", "MPa"),
    "Yield Strength (MPa)":   ("YieldStrength",   "MPa"),
    "Elongation (%)":         ("Elongation",      "%"),
    "Hardness (Rockwell)":    ("Hardness",        None),
    "Elastic Modulus (E, GPa)": ("ElasticModulus","GPa"),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("xlsx->graphdb")

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def normalize_ascii(s: Any) -> str:
    """Normalize Excel quirks: fancy dashes, NBSP, trailing time."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s)
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-").replace("\u00A0", " ")
    s = re.sub(r"\s+00:00:00$", "", s)      # Excel date-time tails
    s = re.sub(r"\s+", " ", s).strip()
    return s

def iri_local(s: str) -> str:
    s = normalize_ascii(s).replace("/", "_")
    out = "".join(ch if ch.isalnum() or ch in "_+.-" else "_" for ch in s)
    if out and out[0].isdigit():
        out = "_" + out
    return out

def mint(prefix: str, hint: str) -> URIRef:
    return URIRef(BASE + f"{prefix}_{iri_local(hint)}_{uuid.uuid4().hex[:8]}")

def mint_stable(prefix: str, hint: str) -> URIRef:
    return URIRef(BASE + f"{prefix}_{iri_local(hint)}")

# -----------------------------------------------------------------------------
# Numeric parsers
# -----------------------------------------------------------------------------
RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-]\s*(\d+(?:\.\d+)?)")
NUM_RE   = re.compile(r"\d+(?:\.\d+)?")

def parse_range_numbers(s: str) -> Optional[Tuple[float, float]]:
    """
    Find an explicit 'a-b' range (ASCII hyphen). Ignore minus as a sign.
    Works even if Excel added junk after, e.g., '10-05 00:00:00'.
    """
    s = normalize_ascii(s)
    m = RANGE_RE.search(s)
    if not m:
        return None
    a = float(m.group(1)); b = float(m.group(2))
    lo, hi = (a, b) if a <= b else (b, a)
    return lo, hi

def parse_single_number(s: str) -> Optional[float]:
    s = normalize_ascii(s)
    m = NUM_RE.search(s)
    return float(m.group(0)) if m else None

# -----------------------------------------------------------------------------
# Cell parsers
# -----------------------------------------------------------------------------
def parse_chem_cell(s: Any) -> Optional[Dict[str, Any]]:
    """
    Accepts 'BAL', '>=x', '<=x', 'a-b', 'x', '-', '' (and tolerates original ≥ ≤ and Excel time tails).
    """
    t = normalize_ascii(s)
    if t in ("", "-"):
        return None
    if t.upper() in ("BAL", "BAL.", "BALANCE"):
        return {"balance": True}

    if t.startswith(">=") or t.startswith("≥"):
        v = parse_single_number(t)
        return {"min": v} if v is not None else None
    if t.startswith("<=") or t.startswith("≤"):
        v = parse_single_number(t)
        return {"max": v} if v is not None else None

    r = parse_range_numbers(t)
    if r:
        lo, hi = r
        return {"min": lo, "max": hi}

    v = parse_single_number(t)
    return {"value": v} if v is not None else None

def parse_mech_cell(prop: str, s: Any) -> Optional[Dict[str, Any]]:
    """
    Tensile/Yield/Elongation: 'a-b' or 'x'
    Hardness: 'HRB75-90' or 'HRC35' (case-insensitive)
    Elastic Modulus: 'x' or '~x'
    """
    t = normalize_ascii(s)
    if t in ("", "-"):
        return None

    approx = False
    if prop == "Elastic Modulus (E, GPa)" and (t.startswith("~") or t.startswith("≈") or t.startswith("∼")):
        approx = True
        t = t[1:].strip()

    if prop == "Hardness (Rockwell)":
        m = re.match(r"^HR([BC])\s*(\d+)(?:\s*-\s*(\d+))?$", t, flags=re.I)
        if m:
            scale = f"HR{m.group(1).upper()}"
            if m.group(3):
                a = float(m.group(2)); b = float(m.group(3))
                lo, hi = (a, b) if a <= b else (b, a)
                return {"min": lo, "max": hi, "scale": scale}
            else:
                return {"value": float(m.group(2)), "scale": scale}
        # Fallback: if someone wrote just '75-90'
        r = parse_range_numbers(t)
        if r:
            lo, hi = r
            return {"min": lo, "max": hi}

    # Generic numeric range
    r = parse_range_numbers(t)
    if r:
        lo, hi = r
        d = {"min": lo, "max": hi}
        if prop == "Elastic Modulus (E, GPa)" and approx:
            d["approximate"] = True
        return d

    # Single number
    v = parse_single_number(t)
    if v is not None:
        d = {"value": v}
        if prop == "Elastic Modulus (E, GPa)" and approx:
            d["approximate"] = True
        return d

    return None

# -----------------------------------------------------------------------------
# RDF helpers
# -----------------------------------------------------------------------------
def add_quantity(g: Graph, unit: Optional[str], data: Dict[str, Any]) -> URIRef:
    """
    Create a Quantity and **guarantee** min <= max if both provided.
    """
    q = mint("Qty", unit or "qty")
    g.add((q, RDF.type, NS.Quantity))
    if unit:
        g.add((q, NS.unitSymbol, Literal(unit)))

    # safety swap if needed
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
    if data.get("approximate"):
        g.add((q, NS.isApproximate, Literal(True, datatype=XSD.boolean)))
    return q

def add_comp_entry(g: Graph, comp_uri: URIRef, elem_uri: URIRef, data: Dict[str, Any]):
    entry = mint("Entry", f"{Path(str(elem_uri)).name}")
    g.add((entry, RDF.type, NS.CompositionEntry))
    g.add((comp_uri, NS.hasComponent, entry))
    g.add((entry, NS.element, elem_uri))
    if data.get("balance"):
        g.add((entry, NS.isBalanceRemainder, Literal(True, datatype=XSD.boolean)))
    else:
        q_uri = add_quantity(g, "wt%", data)
        g.add((entry, NS.hasMassFraction, q_uri))

# -----------------------------------------------------------------------------
# Build graph from XLSX
# -----------------------------------------------------------------------------
def build_graph(xlsx_path: str) -> Graph:
    log.info("Reading Excel: %s", xlsx_path)

    dfc = pd.read_excel(xlsx_path, sheet_name=SHEET_COMPOSITION, engine="openpyxl", dtype=str).fillna("")
    dfm = pd.read_excel(xlsx_path, sheet_name=SHEET_MECHANICAL,  engine="openpyxl", dtype=str).fillna("")

    # Normalize alloy names (and dashes)
    for df in (dfc, dfm):
        df["Alloy"] = df["Alloy"].apply(normalize_ascii)

    g = Graph()
    g.bind("ns", NS); g.bind("rdf", RDF); g.bind("rdfs", RDFS); g.bind("xsd", XSD)

    # Element IRIs from columns (except Alloy, Others)
    elem_cols = [c for c in dfc.columns if c not in {"Alloy", "Others"}]
    for sym in elem_cols:
        e_uri = mint_stable("Element", sym)
        g.add((e_uri, RDF.type, NS.Element))
        g.add((e_uri, RDFS.label, Literal(sym)))

    # Alloys and their composition nodes
    alloys = sorted(set(dfc["Alloy"].tolist() + dfm["Alloy"].tolist()))
    for name in alloys:
        a_uri = mint_stable("Alloy", name)
        g.add((a_uri, RDF.type, NS.NickelBasedSuperalloy))
        g.add((a_uri, RDFS.label, Literal(name)))
        g.add((a_uri, NS.tradeDesignation, Literal(name)))

        c_uri = mint_stable("Comp", name)
        g.add((c_uri, RDF.type, NS.Composition))
        g.add((a_uri, NS.hasComposition, c_uri))

    # Composition rows
    for _, row in dfc.iterrows():
        alloy = normalize_ascii(row["Alloy"])
        c_uri = mint_stable("Comp", alloy)

        others = normalize_ascii(row.get("Others", ""))
        if others:
            g.add((c_uri, NS.otherConstituents, Literal(others)))

        for sym in elem_cols:
            raw = normalize_ascii(row.get(sym, ""))
            data = parse_chem_cell(raw)
            if data:
                add_comp_entry(g, c_uri, mint_stable("Element", sym), data)

    # Mechanical rows
    for _, row in dfm.iterrows():
        alloy = normalize_ascii(row["Alloy"])
        a_uri = mint_stable("Alloy", alloy)

        for col, (prop_class, default_unit) in PROPERTY_MAP.items():
            cell = normalize_ascii(row.get(col, ""))
            if not cell:
                continue
            parsed = parse_mech_cell(col, cell)
            if not parsed:
                continue

            meas = mint("Meas", f"{alloy}_{prop_class}")
            g.add((meas, RDF.type, NS.Measurement))
            g.add((a_uri, NS.hasMeasurement, meas))
            g.add((meas, NS.measures, URIRef(BASE + prop_class)))

            unit = parsed.get("scale", default_unit)
            q_uri = add_quantity(g, unit, parsed)
            g.add((meas, NS.hasQuantity, q_uri))

    log.info("Graph built with %d triples", len(g))
    return g

# -----------------------------------------------------------------------------
# Upload
# -----------------------------------------------------------------------------
def upload_graph(g: Graph):
    ttl_bytes = g.serialize(format="turtle").encode("utf-8")
    log.info("Uploading %d triples directly to GraphDB…", len(g))

    endpoint = f"{GRAPHDB_URL}/repositories/{REPO_ID}/statements"
    params   = {"context": f"<{NAMED_GRAPH}>"}
    headers  = {"Content-Type": "text/turtle; charset=UTF-8"}

    resp = requests.post(endpoint, params=params, data=ttl_bytes, headers=headers, timeout=120)
    if resp.status_code // 100 != 2:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    log.info("✅ Uploaded to %s (repo %s)", NAMED_GRAPH, REPO_ID)

# -----------------------------------------------------------------------------
def main():
    if not Path(XLSX_FILE).exists():
        raise SystemExit(f"Missing Excel file: {XLSX_FILE}")
    g = build_graph(XLSX_FILE)
    upload_graph(g)

if __name__ == "__main__":
    main()
