from __future__ import annotations

import os
import re
import sys
import unicodedata
import logging
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from functools import lru_cache
from collections import defaultdict

import weaviate
from weaviate.classes.query import QueryReference

# ---- logging -----------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("superalloy_rag")


# ---- settings ----------------------------------------------------------------
@dataclass
class Settings:
    weaviate_host: str = os.getenv("WEAVIATE_HOST", "localhost")
    weaviate_port: int = int(os.getenv("WEAVIATE_PORT", 8081))
    weaviate_grpc_port: int = int(os.getenv("WEAVIATE_GRPC_PORT", 50052))
    collection_name: str = os.getenv("WEAVIATE_COLLECTION", "NickelBasedSuperalloy")

    ollama_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    llm_model: str = os.getenv("LLM_MODEL", "llama3.2")
    narrate_summary: bool = os.getenv("NARRATE_SUMMARY", "0").strip().lower() in ("1", "true", "yes")

    exclude_weld: bool = os.getenv("EXCLUDE_WELD_CONSUMABLES", "1").strip().lower() not in ("0", "false")
    max_fetch_objects: int = int(os.getenv("MAX_FETCH_OBJECTS", 500))
    max_context_alloys: int = int(os.getenv("MAX_CONTEXT_ALLOYS", 50))
    max_present_alloys: int = int(os.getenv("MAX_PRESENT_ALLOYS", 20))
    cache_ttl: int = int(os.getenv("CACHE_TTL_SECONDS", 300))


# ---- cache -------------------------------------------------------------------
_CACHE: Dict[str, Tuple[str, float]] = {}


def _cache_key(q: str) -> str:
    return hashlib.md5(q.encode()).hexdigest()


def _get_cached(q: str, ttl: int) -> Optional[str]:
    key = _cache_key(q)
    if key in _CACHE:
        result, timestamp = _CACHE[key]
        if time.time() - timestamp < ttl:
            logger.info("Cache hit")
            return result
    return None


def _set_cached(q: str, result: str):
    _CACHE[_cache_key(q)] = (result, time.time())


# ---- small helpers ------------------------------------------------------------
def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"\s+", " ", s).strip()


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _fmt_num(x: Optional[float]) -> str:
    if x is None:
        return "?"
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}"
    return f"{x:.2f}"


def _short(s: str, n: int = 24) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


@lru_cache(maxsize=128)
def _extract_base_designation(name: str) -> str:
    name = normalize(name)
    pats = [
        r"(Inconel\s*\d+[A-Z]*)",
        r"(Hastelloy\s*[A-Za-z0-9\-]+)",
        r"(Rene\s*\d+)",
        r"(Rene\s+[A-Za-z]+)",  # Rene Supersolvus, Rene N4, etc.
        r"(CMSX-?\d+)",
        r"(MAR-?M\d+)",
        r"(Nimonic\s*\d+)",
        r"(Udimet\s*\d+)",
        r"(Waspaloy)",
        r"(Astroloy)",
        r"(Incoloy\s*\d+[A-Z]*)",
        r"(Haynes\s*\d+)",
    ]
    for p in pats:
        m = re.search(p, name, re.IGNORECASE)
        if m:
            return normalize(m.group(1))
    return name


def _validate_query(q: str) -> Tuple[bool, Optional[str]]:
    if not q or not q.strip():
        return False, "Empty query"
    if len(q) > 2000:
        return False, "Query too long (max 2000 chars)"
    dangerous = ["<script", "javascript:", "onerror=", "eval("]
    if any(d in q.lower() for d in dangerous):
        return False, "Invalid query pattern detected"
    return True, None


# ---- data containers ----------------------------------------------------------
@dataclass
class CompositionEntry:
    element: str
    value_str: str
    min_v: Optional[float]
    max_v: Optional[float]
    numeric: Optional[float]


@dataclass
class PropertyMeasurement:
    name: str
    type: str
    value_str: str
    unit: str
    numeric_raw: Optional[float]
    numeric_norm: Optional[float]
    unit_norm: Optional[str]
    temperature: Optional[str]
    heat_treatment: Optional[str]
    stress: Optional[float] = None
    life_hours: Optional[float] = None


@dataclass
class VariantRecord:
    name: str
    properties: List[PropertyMeasurement]


@dataclass
class AlloyRecord:
    uuid: str
    name: str
    uns: Optional[str]
    family: Optional[str] = None
    density: Optional[float] = None
    gamma_prime: Optional[float] = None
    heat_treatment: Optional[str] = None
    composition: List[CompositionEntry] = field(default_factory=list)
    properties: List[PropertyMeasurement] = field(default_factory=list)
    variants: List[VariantRecord] = field(default_factory=list)


# ---- element map + robust tokens ---------------------------------------------
NAME_TO_SYMBOL: Dict[str, str] = {
    "nickel": "Ni", "chromium": "Cr", "chrome": "Cr", "iron": "Fe", "cobalt": "Co",
    "molybdenum": "Mo", "niobium": "Nb", "columbium": "Nb", "titanium": "Ti",
    "aluminum": "Al", "aluminium": "Al", "carbon": "C", "boron": "B", "silicon": "Si",
    "manganese": "Mn", "tungsten": "W", "vanadium": "V", "zirconium": "Zr", "yttrium": "Y",
    "copper": "Cu", "phosphorus": "P", "sulfur": "S", "sulphur": "S", "nitrogen": "N",
    "tantalum": "Ta", "rhenium": "Re",
}
TOKEN_TO_SYM: Dict[str, str] = {}
for name, sym in NAME_TO_SYMBOL.items():
    TOKEN_TO_SYM[name.lower()] = sym
for sym in set(NAME_TO_SYMBOL.values()):
    TOKEN_TO_SYM[sym.lower()] = sym
_ELEM_TOKENS = sorted(TOKEN_TO_SYM.keys(), key=len, reverse=True)
_ELEM_REGEX = r"(?:\b" + r"\b|\b".join(re.escape(t) for t in _ELEM_TOKENS) + r"\b)"


# ---- property unit normalization ---------------------------------------------
def _normalize_property_unit(ptype: str, name: str, numeric: Optional[float], unit: str) -> Tuple[
    Optional[float], Optional[str]]:
    if numeric is None:
        return None, None
    u = (unit or "").strip().lower()
    p = (ptype or "").lower()
    nm = (name or "").lower()

    def is_strength():
        return ("tensile" in p or "tensile" in nm or "ultimate" in nm or "uts" in nm
                or "yield" in p or "yield" in nm or "proof" in nm)

    def is_modulus():
        return "modulus" in p or "modulus" in nm or "young" in nm or "elastic" in p

    def is_elong():
        return "elong" in p or "elong" in nm or "%" in u

    def is_hardness():
        return ("hardness" in p or "hardness" in nm or u.upper().startswith(("HR", "HB", "HV")))

    if is_strength():
        if u in ("mpa", "n/mm^2", "n/mm2"): return float(numeric), "MPa"
        if u == "gpa":                      return float(numeric) * 1000.0, "MPa"
        if u == "pa":                       return float(numeric) / 1e6, "MPa"
        if u == "ksi":                      return float(numeric) * 6.894757, "MPa"
        if u == "psi":                      return float(numeric) * 0.006894757, "MPa"
        return None, None

    if is_modulus():
        if u == "gpa": return float(numeric), "GPa"
        if u == "mpa": return float(numeric) / 1000.0, "GPa"
        if u == "pa":  return float(numeric) / 1e9, "GPa"
        if u == "psi": return float(numeric) * 6.894757e-6, "GPa"
        if u == "ksi": return float(numeric) * 6.894757e-3, "GPa"
        return None, None

    if is_elong():
        return float(numeric), "%"

    if is_hardness():
        return float(numeric), unit.upper() or "H?"

    return None, None


# ---- minimal Ollama client ----------------------------------------------------
class Ollama:
    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 200) -> str:
        try:
            import requests
            url = f"{self.host}/api/generate"
            payload = {
                "model": self.model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "options": {"temperature": temperature},
            }
            r = requests.post(url, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return ""


# ---- connection pool ----------------------------------------------------------
_WEAVIATE_CLIENT: Optional[weaviate.WeaviateClient] = None


def _get_weaviate_client(settings: Settings) -> weaviate.WeaviateClient:
    global _WEAVIATE_CLIENT
    if _WEAVIATE_CLIENT is None:
        _WEAVIATE_CLIENT = weaviate.connect_to_local(
            host=settings.weaviate_host,
            port=settings.weaviate_port,
            grpc_port=settings.weaviate_grpc_port,
        )
    return _WEAVIATE_CLIENT


# ---- core RAG -----------------------------------------------------------------
class SuperalloyRAG:
    def __init__(self, question: str, settings: Optional[Settings] = None, use_cache: bool = True):
        self.question = normalize(question)
        self.settings = settings or Settings()
        self.use_cache = use_cache

        self.client = _get_weaviate_client(self.settings)
        self.alloy_coll = self.client.collections.get(self.settings.collection_name)
        self._alloy_data: List[AlloyRecord] = []

        self.llm = Ollama(self.settings.ollama_host, self.settings.llm_model)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    _RE_UNS = re.compile(r"\bUNS\s*(N\s*\d{5})\b", re.IGNORECASE)
    _RE_UNS_SIMPLE = re.compile(r"\bN\d{5}\b", re.IGNORECASE)
    _RE_ALNUM_SERIES = re.compile(r"\b([A-Za-z][A-Za-z\-\u00E9\u00E8]{2,}\s*(?:\d{2,3}[A-Z]?(?:-?[A-Z0-9]+)?))\b")

    def _classify(self) -> str:
        q = self.question.lower()

        # NEW: Detect variant queries
        if re.search(r"\b(variant|variants|version|versions|form|forms|condition|conditions)\b", q):
            return "variants"

        # Detect property queries (even without "highest/lowest")
        if re.search(r"\b(propert(y|ies)|mechanical|physical|thermal|strength|hardness|modulus|elongation|density)\b",
                     q):
            # If also asking about variants
            if re.search(r"\b(each|every|all)\b", q):
                return "variants"
            # If not asking for extreme
            if not re.search(r"\b(highest|maximum|max|lowest|minimum|min|strongest|weakest)\b", q):
                return "properties"

        if re.search(r"\b(compare|versus|vs\.?|diff(erence)?)\b", q):
            return "compare"
        if re.search(r"\b(highest|maximum|max|lowest|minimum|min|strongest|weakest)\b", q) and \
                re.search(r"\b(tensile|yield|elongation|hardness|elastic|young|modulus|strength)\b", q):
            return "extreme_property"
        th_words = ("more than", "over", "above", "at least", "no less than", "less than", "below", "under",
                    "no more than", ">=", "<=", ">", "<")
        if any(w in q for w in th_words) and "%" in q:
            el_present = re.search(_ELEM_REGEX, q, re.IGNORECASE) is not None
            if el_present:
                return "filtering"
        if re.search(r"\b(comp|composition|wt%|weight percent|chemical|elements?)\b", q):
            return "composition"
        return "general"

    def _extract_mentions(self) -> Dict[str, List[str]]:
        uns_matches = [m.strip().replace(" ", "") for m in
                       (self._RE_UNS.findall(self.question) + self._RE_UNS_SIMPLE.findall(self.question))]
        desig_matches = [normalize(m) for m in self._RE_ALNUM_SERIES.findall(self.question)]
        desig_matches = [re.sub(r"Ren[eé]", "Rene", m, flags=re.IGNORECASE) for m in desig_matches]
        STOP = {"than", "over", "under", "below", "above", "least", "more", "less"}
        desig_matches = [d for d in desig_matches if d and d.split()[0].lower() not in STOP]

        def _dedup(seq: Iterable[str]) -> List[str]:
            seen = set();
            out = []
            for s in seq:
                key = s.lower()
                if key not in seen:
                    seen.add(key);
                    out.append(s)
            return out

        return {"uns": _dedup(uns_matches), "designations": _dedup(desig_matches)}

    def _strict_designation_match(self, name: str, mentions: Dict[str, List[str]]) -> bool:
        name_l = (name or "").lower()
        if not (mentions["uns"] or mentions["designations"]):
            return True
        for u in mentions["uns"]:
            if u.lower() in name_l:
                return True
        for desig in mentions["designations"]:
            d = (desig or "").lower().strip()
            if not d:
                continue
            parts = d.replace("\t", " ").replace("  ", " ").split()
            fam = parts[0] if parts else ""
            series = None
            for tok in d.replace("-", " ").split():
                if any(ch.isdigit() for ch in tok):
                    series = tok
                    break
            if fam:
                fam = fam.replace("rené", "rene")
                if series:
                    fam_ok = (fam in name_l) or (
                                fam == "inconel" and re.search(rf"\bin[-\s]?{re.escape(series)}\b", name_l))
                    ser_ok = re.search(rf"\b{re.escape(series)}\b", name_l) is not None
                    if fam_ok and ser_ok:
                        return True
                else:
                    if fam in name_l:
                        return True
            else:
                if d in name_l:
                    return True
        return False

    def _postfilter_objects(self, objects: List[Any], mentions: Dict[str, List[str]], mode: str) -> List[Any]:
        out: List[Any] = []
        for obj in objects:
            name = (obj.properties or {}).get("tradeDesignation", "") or ""
            nl = name.lower()
            if self.settings.exclude_weld and mode in ("composition", "filtering", "properties", "variants"):
                if "filler" in nl or "weld" in nl or "weldment" in nl:
                    continue
            if mentions["uns"] or mentions["designations"]:
                if not self._strict_designation_match(name, mentions):
                    continue
            out.append(obj)
        return out or objects

    def _retrieve_candidates(self, mentions: Dict[str, List[str]], mode: str) -> List[Any]:
        objects: List[Any] = []
        if mentions["uns"] or mentions["designations"]:
            qlist = mentions["uns"] + mentions["designations"]
            seen = set()
            for q in qlist:
                try:
                    res = self.alloy_coll.query.bm25(
                        query=q,
                        limit=50,
                        return_properties=["tradeDesignation", "unsNumber"],
                    )
                    for obj in res.objects:
                        if obj.uuid in seen:
                            continue
                        name = (obj.properties or {}).get("tradeDesignation", "")
                        if self._strict_designation_match(name, mentions):
                            objects.append(obj)
                            seen.add(obj.uuid)
                except Exception as e:
                    logger.warning(f"BM25 query failed for '{q}': {e}")
            if not objects:
                logger.info("No strict matches from BM25; falling back to full fetch")
        if not objects:
            try:
                lim = self.settings.max_fetch_objects if mode in {"compare", "filtering", "extreme_property",
                                                                  "variants", "properties"} else 200
                fetched = self.alloy_coll.query.fetch_objects(limit=lim,
                                                              return_properties=["tradeDesignation", "unsNumber"])
                objects = fetched.objects
            except Exception as e:
                logger.error(f"Fetch objects failed: {e}")
                return []
        logger.info(f"Retrieved {len(objects)} candidate objects")
        objects = self._postfilter_objects(objects, mentions, mode)
        logger.info(f"Post-filtered to {len(objects)} objects")
        return objects

    def _get_full_alloy(self, alloy_uuid: str) -> Optional[Any]:
        try:
            return self.alloy_coll.query.fetch_object_by_id(
                uuid=alloy_uuid,
                return_properties=["tradeDesignation", "unsNumber", "family", "density", "gammaPrimeVolPct", "typicalHeatTreatment"],
                return_references=[
                    QueryReference(
                        link_on="hasComposition",
                        return_references=[
                            QueryReference(
                                link_on="hasComponent",
                                return_properties=["isBalanceRemainder"],
                                return_references=[
                                    QueryReference(link_on="hasElement", return_properties=["symbol", "label"]),
                                    QueryReference(
                                        link_on="hasMassFraction",
                                        return_properties=["numericValue", "minInclusive", "maxInclusive", "nominal",
                                                           "unitSymbol"],
                                    ),
                                ],
                            )
                        ],
                    ),
                    QueryReference(
                        link_on="hasVariant",
                        return_properties=["variantName", "sourceUrl"],
                        return_references=[
                            QueryReference(
                                link_on="hasPropertySet",
                                return_references=[
                                    QueryReference(link_on="measuresProperty",
                                                   return_properties=["name", "propertyType"]),
                                    QueryReference(
                                        link_on="hasMeasurement",
                                        return_properties=["stress", "lifeHours"],
                                        return_references=[
                                            QueryReference(
                                                link_on="hasQuantity",
                                                return_properties=["numericValue", "minInclusive", "maxInclusive",
                                                                   "nominal", "unitSymbol"],
                                            ),
                                            QueryReference(
                                                link_on="hasTestCondition",
                                                return_properties=["temperatureCategory", "heatTreatmentCondition"],
                                            ),
                                        ],
                                    ),
                                ],
                            )
                        ],
                    ),
                ],
            )
        except Exception as e:
            logger.warning(f"Fetch error for {alloy_uuid}: {e}")
            return None

    @staticmethod
    def _first(obj: Any, key: str) -> Optional[Any]:
        try:
            if not obj.references or key not in obj.references:
                return None
            arr = obj.references[key].objects
            return arr[0] if arr else None
        except Exception:
            return None

    def _parse_composition(self, alloy_obj: Any) -> List[CompositionEntry]:
        out: List[CompositionEntry] = []
        comp = self._first(alloy_obj, "hasComposition")
        if not comp:
            return out
        comps = getattr(comp.references.get("hasComponent", None), "objects", []) if comp.references else []
        for entry in comps:
            elem_obj = self._first(entry, "hasElement")
            if not elem_obj:
                continue
            symbol = (elem_obj.properties or {}).get("symbol", "?")
            is_balance = (entry.properties or {}).get("isBalanceRemainder", False)
            if is_balance:
                out.append(CompositionEntry(symbol, "Balance", None, None, None))
                continue
            qty = self._first(entry, "hasMassFraction")
            if not qty:
                continue
            p = qty.properties or {}
            num = p.get("numericValue")
            mn = p.get("minInclusive")
            mx = p.get("maxInclusive")
            nom = p.get("nominal")
            unit = p.get("unitSymbol") or "%"

            if num is not None:
                val_s = f"{num} {unit}"
                numeric = float(num)
            elif nom is not None:
                val_s = f"{nom} {unit}"
                numeric = float(nom)
            elif mn is not None and mx is not None:
                val_s = f"{mn}-{mx} {unit}"
                numeric = (float(mn) + float(mx)) / 2
            elif mn is not None:
                val_s = f"≥{mn} {unit}"
                numeric = float(mn)
            elif mx is not None:
                val_s = f"≤{mx} {unit}"
                numeric = float(mx)
            else:
                val_s = f"? {unit}"
                numeric = None

            out.append(CompositionEntry(symbol, val_s, _to_float(mn), _to_float(mx), numeric))
        return out

    def _parse_variants(self, alloy_obj: Any) -> List[VariantRecord]:
        out: List[VariantRecord] = []
        variants = getattr(alloy_obj.references.get("hasVariant", None), "objects", []) if alloy_obj.references else []
        for variant in variants:
            v_name = (variant.properties or {}).get("variantName", "Default")
            v_props: List[PropertyMeasurement] = []
            
            prop_sets = getattr(variant.references.get("hasPropertySet", None), "objects",
                                []) if variant.references else []
            for ps in prop_sets:
                mp = self._first(ps, "measuresProperty")
                ptype = (mp.properties or {}).get("propertyType", "Unknown") if mp else "Unknown"
                pname = (mp.properties or {}).get("name", ptype) if mp else ptype
                meas_list = getattr(ps.references.get("hasMeasurement", None), "objects", []) if ps.references else []
                for m in meas_list:
                    qty = self._first(m, "hasQuantity")
                    if not qty:
                        continue
                    qp = qty.properties or {}
                    num = qp.get("numericValue")
                    mn = qp.get("minInclusive")
                    mx = qp.get("maxInclusive")
                    nom = qp.get("nominal")
                    unit = qp.get("unitSymbol") or ""
                    if num is not None:
                        value = f"{num} {unit}".strip()
                        numeric = float(num)
                    elif nom is not None:
                        value = f"{nom} {unit}".strip()
                        numeric = float(nom)
                    elif mn is not None and mx is not None:
                        value = f"{mn}-{mx} {unit}".strip()
                        numeric = (float(mn) + float(mx)) / 2
                    elif mn is not None:
                        value = f"≥{mn} {unit}".strip()
                        numeric = float(mn)
                    elif mx is not None:
                        value = f"≤{mx} {unit}".strip()
                        numeric = float(mx)
                    else:
                        value = f"? {unit}".strip()
                        numeric = None
                    tc = self._first(m, "hasTestCondition")
                    temp = (tc.properties or {}).get("temperatureCategory") if tc else None
                    ht = (tc.properties or {}).get("heatTreatmentCondition") if tc else None
                    
                    # Creep Rupture specific fields
                    stress = (m.properties or {}).get("stress")
                    life_hours = (m.properties or {}).get("lifeHours")
                    
                    if ptype == "CreepRupture" and stress is not None and life_hours is not None:
                        value = f"{stress} MPa / {life_hours} hrs"
                        numeric = float(life_hours) # Use life hours for sorting/filtering if needed
                    
                    numeric_norm, unit_norm = _normalize_property_unit(ptype, pname, numeric, unit)
                    v_props.append(
                        PropertyMeasurement(pname, ptype, value, unit, numeric, numeric_norm, unit_norm, temp, ht, stress, life_hours))
            out.append(VariantRecord(v_name, v_props))
        return out

    def _build_context(self, candidates: List[Any]) -> List[AlloyRecord]:
        out: List[AlloyRecord] = []
        for obj in candidates[: self.settings.max_context_alloys]:
            full = self._get_full_alloy(obj.uuid)
            if not full:
                continue
            name = (full.properties or {}).get("tradeDesignation", "Unknown")
            parsed_variants = self._parse_variants(full)
            all_props = [p for v in parsed_variants for p in v.properties]
            
            rec = AlloyRecord(
                uuid=full.uuid,
                name=name,
                uns=(full.properties or {}).get("unsNumber"),
                family=(full.properties or {}).get("family"),
                density=(full.properties or {}).get("density"),
                gamma_prime=(full.properties or {}).get("gammaPrimeVolPct"),
                heat_treatment=(full.properties or {}).get("typicalHeatTreatment"),
                composition=self._parse_composition(full),
                properties=all_props,
                variants=parsed_variants,
            )
            out.append(rec)
        logger.info(f"Context built for {len(out)} alloys")
        return out

    def _format_properties_comprehensive(self, properties: List[PropertyMeasurement]) -> List[str]:
        """Format ALL properties, grouped by type, with conditions"""
        if not properties:
            return ["  No property data available"]

        # Group by property type
        by_type: Dict[str, List[PropertyMeasurement]] = defaultdict(list)
        for p in properties:
            if p.value_str and p.value_str != "?":
                by_type[p.type].append(p)

        if not by_type:
            return ["  No property data available"]

        lines: List[str] = []

        # Priority order for common properties
        priority_types = [
            "TensileStrength", "YieldStrength", "Elongation",
            "Hardness", "CreepRupture", "ElasticModulus", "Density"
        ]

        # Show priority properties first
        for ptype in priority_types:
            if ptype in by_type:
                lines.append(f"\n  {ptype}:")
                for p in by_type[ptype]:
                    cond = []
                    if p.temperature:
                        cond.append(f"Temp: {p.temperature}")
                    if p.heat_treatment:
                        cond.append(f"HT: {p.heat_treatment}")
                    cond_str = f" ({', '.join(cond)})" if cond else ""
                    lines.append(f"    • {p.value_str}{cond_str}")

        # Show remaining properties
        remaining = [k for k in sorted(by_type.keys()) if k not in priority_types]
        if remaining:
            lines.append("\n  Other Properties:")
            for ptype in remaining:
                lines.append(f"    {ptype}:")
                for p in by_type[ptype][:3]:  # Limit to 3 per type
                    cond = []
                    if p.temperature:
                        cond.append(f"Temp: {p.temperature}")
                    if p.heat_treatment:
                        cond.append(f"HT: {p.heat_treatment}")
                    cond_str = f" ({', '.join(cond)})" if cond else ""
                    lines.append(f"      • {p.value_str}{cond_str}")

        return lines

    def _answer_composition(self, mentions: Dict[str, List[str]]) -> str:
        def _is_mentioned(rec: AlloyRecord) -> bool:
            return self._strict_designation_match(rec.name, mentions) or (
                        rec.uns and any(u.lower() in rec.uns.lower() for u in mentions["uns"]))

        focus = [r for r in self._alloy_data if _is_mentioned(r)] or self._alloy_data
        focus = focus[: self.settings.max_present_alloys]

        if not focus:
            return "No matching alloys found in the database."

        parts: List[str] = []
        seen_groups: Dict[str, List[AlloyRecord]] = {}
        for r in focus:
            key = _extract_base_designation(r.name)
            seen_groups.setdefault(key, []).append(r)

        for base, group in seen_groups.items():
            if len(group) > 1:
                parts.append(f"\n{'=' * 70}\nALLOY: {base} ({len(group)} variants)\n{'=' * 70}")
            for r in group:
                if len(group) > 1:
                    parts.append(f"\n— Variant: {r.name}  |  UNS: {r.uns or 'N/A'}")
                else:
                    parts.append(f"\n{'=' * 70}\nALLOY: {r.name}\n{'=' * 70}\nUNS: {r.uns or 'N/A'}")
                if r.composition:
                    parts.append("\nCOMPOSITION (wt%):")
                    for c in sorted(r.composition, key=lambda x: (x.element != 'Ni', -float(x.numeric or 0))):
                        parts.append(f"  {c.element:>3}: {c.value_str}")
                else:
                    parts.append("\nCOMPOSITION: No data available")

                if r.properties:
                    parts.append("\nPROPERTIES:")
                    parts.extend(self._format_properties_comprehensive(r.properties))
                else:
                    parts.append("\nPROPERTIES: No data available")

        return "\n".join(parts)

    def _answer_properties(self) -> str:
        """NEW: Dedicated properties answer with full detail"""
        if not self._alloy_data:
            return "No matching alloys found."

        focus = self._alloy_data[: self.settings.max_present_alloys]
        parts: List[str] = []

        for r in focus:
            parts.append(f"\n{'=' * 70}\nALLOY: {r.name}\n{'=' * 70}")
            parts.append(f"UNS: {r.uns or 'N/A'}")
            if r.family: parts.append(f"Family: {r.family}")
            if r.density: parts.append(f"Density: {r.density} g/cm³")
            if r.gamma_prime: parts.append(f"Gamma Prime: {r.gamma_prime} vol%")
            if r.heat_treatment: parts.append(f"Typical HT: {r.heat_treatment}")

            if r.properties:
                parts.append("\nPROPERTIES:")
                parts.extend(self._format_properties_comprehensive(r.properties))
            else:
                parts.append("\nPROPERTIES: No data available in database")
                parts.append("This may mean:")
                parts.append("  • Property data not yet imported for this alloy")
                parts.append("  • Alloy exists but lacks test data")
                parts.append("  • Check variant-specific designations")

        return "\n".join(parts)

    def _answer_variants(self) -> str:
        """NEW: Show all variants with their properties"""
        if not self._alloy_data:
            return "No matching alloys found."

        # Group by base designation
        groups: Dict[str, List[AlloyRecord]] = defaultdict(list)
        for r in self._alloy_data:
            base = _extract_base_designation(r.name)
            groups[base].append(r)

        parts: List[str] = []

        for base, variants in groups.items():
            parts.append(f"\n{'=' * 70}\nBASE ALLOY: {base}\n{'=' * 70}")
            parts.append(f"Found {len(variants)} variant(s):\n")

            for i, r in enumerate(variants, 1):
                parts.append(f"\n{'—' * 35}")
                parts.append(f"VARIANT {i}: {r.name}") # This is the Alloy Name, but we want to show variants inside
                
                if r.variants:
                    for j, v in enumerate(r.variants, 1):
                         parts.append(f"\n  • Sub-Variant {j}: {v.name}")
                         if v.properties:
                             parts.append("    PROPERTIES:")
                             # Indent properties
                             props = self._format_properties_comprehensive(v.properties)
                             for line in props:
                                 parts.append(f"    {line}")
                else:
                    parts.append(f"{'—' * 35}")
                    parts.append(f"UNS: {r.uns or 'N/A'}")

                    if r.composition:
                        parts.append("\nCOMPOSITION (wt%):")
                        for c in sorted(r.composition, key=lambda x: (x.element != 'Ni', -float(x.numeric or 0))):
                            parts.append(f"  {c.element:>3}: {c.value_str}")

                    if r.properties:
                        parts.append("\nPROPERTIES:")
                        parts.extend(self._format_properties_comprehensive(r.properties))
                    else:
                        parts.append("\nPROPERTIES: No data available")

        return "\n".join(parts)

    def _parse_threshold(self) -> Optional[Tuple[str, float, str]]:
        q = (self.question or "").lower()
        ops = [
            (r">=\s*", "≥"), (r"<=\s*", "≤"), (r">\s*", ">"), (r"<\s*", "<"),
            (r"\bmore than\b", ">"), (r"\bover\b", ">"), (r"\babove\b", ">"),
            (r"\bat least\b", "≥"), (r"\bno less than\b", "≥"),
            (r"\bless than\b", "<"), (r"\bbelow\b", "<"), (r"\bunder\b", "<"),
            (r"\bno more than\b", "≤"),
        ]
        for patt, op in ops:
            m = re.search(rf"{patt}\s*(\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?(?P<elem>{_ELEM_REGEX})", q, flags=re.IGNORECASE)
            if not m:
                continue
            thr = float(m.group(1))
            raw = m.group("elem").lower()
            sym = TOKEN_TO_SYM.get(raw)
            if not sym:
                continue
            return sym, thr, op
        return None

    def _answer_filtering(self) -> str:
        parsed = self._parse_threshold()
        if not parsed:
            return "Could not parse a composition threshold from the query."
        elem_sym, thr, op = parsed

        def cmp_fn(val: Optional[float]) -> bool:
            if val is None:
                return False
            return {">": val > thr, "≥": val >= thr, "<": val < thr, "≤": val <= thr}[op]

        matched: List[Tuple[AlloyRecord, float, str, str]] = []
        for r in self._alloy_data:
            elem_num = None
            elem_str = None
            ni_str = None
            for c in r.composition:
                el = (c.element or "").lower()
                if el == elem_sym.lower():
                    num = c.numeric if c.numeric is not None else c.max_v
                    if cmp_fn(num):
                        elem_num = num if num is not None else -1
                        elem_str = c.value_str
                elif el == "ni":
                    ni_str = c.value_str
            if elem_num is not None:
                matched.append((r, float(elem_num), elem_str or "?", ni_str or "?"))

        if not matched:
            return f"No alloys found with {elem_sym} {op} {thr} wt%."

        matched.sort(key=lambda t: t[1] if t[1] is not None else -1, reverse=True)
        matched = matched[: self.settings.max_present_alloys]

        lines = [f"Alloys with {elem_sym} {op} {thr} wt% ({len(matched)} shown):"]
        for r, _, e_str, ni_str in matched:
            lines.append(f"• {r.name} (UNS: {r.uns or 'N/A'}) — {elem_sym}: {e_str} | Ni: {ni_str}")
        return "\n".join(lines)

    def _answer_extreme(self) -> str:
        q = self.question.lower()
        targets = [
            ("TensileStrength", ("tensile", "ultimate", "uts")),
            ("YieldStrength", ("yield", "0.2%", "proof")),
            ("Elongation", ("elongation", "ductility")),
            ("Hardness", ("hardness", "hrc", "brinell", "rockwell", "vickers", "hv", "hbw")),
            ("ElasticModulus", ("elastic", "young", "modulus")),
        ]
        target_type = None
        for ptype, pats in targets:
            if any(re.search(p, q) for p in pats):
                target_type = ptype
                break
        if not target_type:
            return "Property not recognized in the question."

        is_highest = bool(re.search(r"highest|max(imum)?|strongest", q))
        is_lowest = bool(re.search(r"lowest|min(imum)?|weakest", q))
        if not (is_highest or is_lowest):
            is_highest = True

        def temp_rank(t: Optional[str]) -> int:
            if t is None:
                return 2
            t = t.lower()
            return 0 if any(k in t for k in ("rt", "room", "ambient")) else 1

        best: Optional[Tuple[AlloyRecord, PropertyMeasurement]] = None
        for r in self._alloy_data:
            for p in r.properties:
                if p.type != target_type and target_type not in (p.name or ""):
                    continue
                if p.numeric_norm is None or p.unit_norm is None:
                    continue
                if best is None:
                    best = (r, p);
                    continue
                br, bp = best
                swap = False
                if temp_rank(p.temperature) < temp_rank(bp.temperature):
                    swap = True
                elif temp_rank(p.temperature) == temp_rank(bp.temperature):
                    if is_highest and p.numeric_norm > bp.numeric_norm:
                        swap = True
                    if is_lowest and p.numeric_norm < bp.numeric_norm:
                        swap = True
                if swap:
                    best = (r, p)

        if not best:
            return f"No comparable measurements found for {target_type}."
        r, p = best
        direction = "highest" if is_highest else "lowest"
        extra = f" | Temp: {p.temperature}" if p.temperature else ""
        extra += f" | HT: {p.heat_treatment}" if p.heat_treatment else ""
        value_out = f"{_fmt_num(p.numeric_norm)} {p.unit_norm}" if p.unit_norm in ("MPa", "GPa", "%") else p.value_str
        return f"Alloy with {direction} {target_type}:\n• {r.name} (UNS: {r.uns or 'N/A'}) — {value_out}{extra}"

    def _answer_compare(self, mentions: Dict[str, List[str]]) -> str:
        def _is_focus(rec: AlloyRecord) -> bool:
            return self._strict_designation_match(rec.name, mentions)

        focus = [r for r in self._alloy_data if _is_focus(r)]
        if len(focus) < 2:
            names = sorted(self._alloy_data, key=lambda r: r.name.lower())
            focus = names[:2]
        focus = focus[: self.settings.max_present_alloys]

        if not focus:
            return "No alloys available for comparison."

        def comp_summary(r: AlloyRecord, top_n: int = 8) -> str:
            if not r.composition:
                return "(no composition data)"
            ordered = sorted(r.composition, key=lambda c: (c.numeric is not None, c.numeric or 0), reverse=True)
            return ", ".join([f"{c.element}:{_short(c.value_str)}" for c in ordered[:top_n]])

        lines = ["Comparison:"]
        for r in focus:
            lines.append(f"\n• {r.name} (UNS: {r.uns or 'N/A'})")
            lines.append(f"  Composition: {comp_summary(r)}")

            # Show key properties with conditions
            by_type: Dict[str, List[PropertyMeasurement]] = {}
            for p in r.properties:
                if p.numeric_norm is None or p.unit_norm is None:
                    continue
                by_type.setdefault(p.type, []).append(p)

            if by_type:
                lines.append("  Properties:")
                for key in ("TensileStrength", "YieldStrength", "Elongation", "Hardness"):
                    if key in by_type:
                        cand = sorted(by_type[key], key=lambda x: (
                            0 if (x.temperature or "").lower() in ("rt", "room", "ambient") else 1,
                            -(x.numeric_norm or -1)))[0]
                        show = f"{_fmt_num(cand.numeric_norm)} {cand.unit_norm}" if cand.unit_norm in ("MPa", "GPa",
                                                                                                       "%") else cand.value_str
                        lines.append(f"    {key}: {show}")
        return "\n".join(lines)

    def _narrate(self, text: str) -> str:
        if not self.settings.narrate_summary:
            return text
        try:
            system = "You are a materials engineering expert. Only summarize user-provided context. Be concise."
            user = "Summarize in 2 sentences the key points:\n\n" + text
            summary = self.llm.generate(system, user, temperature=0.1, max_tokens=180)
            if summary:
                return text + "\n\nSummary:\n" + summary
        except Exception as e:
            logger.info(f"LLM summary skipped: {e}")
        return text

    def query(self) -> str:
        valid, error = _validate_query(self.question)
        if not valid:
            return f"Invalid query: {error}"

        if self.use_cache:
            cached = _get_cached(self.question, self.settings.cache_ttl)
            if cached:
                return cached

        try:
            mode = self._classify()
            mentions = self._extract_mentions()
            logger.info(f"Mode: {mode} | Mentions: {mentions}")
            candidates = self._retrieve_candidates(mentions, mode)

            if not candidates:
                return "No matching alloys found in the database for your query."

            if mode in ("filtering", "variants", "properties"):
                ctx_cap = min(len(candidates), self.settings.max_fetch_objects)
                self._alloy_data = self._build_context(candidates[:ctx_cap])
            else:
                self._alloy_data = self._build_context(candidates)

            if not self._alloy_data:
                return "No data available for the requested alloys."

            if mode == "composition":
                result = self._narrate(self._answer_composition(mentions))
            elif mode == "properties":
                result = self._narrate(self._answer_properties())
            elif mode == "variants":
                result = self._narrate(self._answer_variants())
            elif mode == "filtering":
                result = self._narrate(self._answer_filtering())
            elif mode == "extreme_property":
                result = self._narrate(self._answer_extreme())
            elif mode == "compare":
                result = self._narrate(self._answer_compare(mentions))
            else:
                lines = ["Results (general):"]
                for r in self._alloy_data[: self.settings.max_present_alloys]:
                    elems = ', '.join(sorted({c.element for c in r.composition})) or 'n/a'
                    lines.append(f"• {r.name} (UNS: {r.uns or 'N/A'}) — elements: {elems}")
                result = self._narrate("\n".join(lines))

            if self.use_cache:
                _set_cached(self.question, result)

            return result

        except Exception as e:
            logger.exception("Query processing failed")
            return f"An error occurred while processing your query: {str(e)}"


if __name__ == "__main__":
    qs = [
        "What is the composition of Inconel 718?",
        "What are the properties of Inconel 625LCF?",
        "Are there any variants of Inconel 625LCF?",
        "Give me properties for each variant of Inconel 625LCF",
    ]
    if len(sys.argv) > 1:
        qs = [" ".join(sys.argv[1:])]
    for q in qs:
        print("\n" + "=" * 80)
        print("Q:", q)
        with SuperalloyRAG(q) as rag:
            ans = rag.query()
        print("\nA:\n" + ans)