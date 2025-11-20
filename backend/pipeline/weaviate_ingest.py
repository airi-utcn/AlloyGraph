import os
import logging
from collections import defaultdict

import weaviate
from weaviate.util import generate_uuid5
from SPARQLWrapper import SPARQLWrapper, JSON

# Config
GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://localhost:7200")
GRAPHDB_REPO = os.getenv("GRAPHDB_REPO", "NiSuperAlloy")
WEAVIATE_HOST = "localhost"
WEAVIATE_PORT = 8081
WEAVIATE_GRPC_PORT = 50052
BASE = "http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy#"
NS = "nisuperalloy"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def uuid5(key):
    return str(generate_uuid5(NS, key))


def to_float(x):
    try:
        return float(x)
    except:
        return None


def to_bool(x):
    if x is None:
        return None
    return str(x).strip().lower() in ("true", "1")


def query_graphdb(sparql_query):
    endpoint = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPO}"
    sp = SPARQLWrapper(endpoint)
    sp.setQuery(sparql_query)
    sp.setReturnFormat(JSON)
    sp.setMethod("POST")
    return sp.query().convert()


def connect_weaviate():
    client = weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_PORT,
        grpc_port=WEAVIATE_GRPC_PORT
    )
    client.is_live()
    return client


def fetch_alloys():
    """Fetch all alloys with pagination."""
    alloys = {}
    offset = 0
    page_size = 100

    log.info("Fetching alloys from GraphDB...")

    while True:
        q = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX ns: <{BASE}>
        SELECT ?alloy ?label ?uns ?comp ?others ?family ?density ?gammaPrime ?heatTreat
        WHERE {{
          ?alloy rdf:type ns:NickelBasedSuperalloy ;
                 ns:tradeDesignation ?label .
          OPTIONAL {{ ?alloy ns:unsNumber ?uns }}
          OPTIONAL {{ ?alloy ns:family ?family }}
          OPTIONAL {{ ?alloy ns:density ?density }}
          OPTIONAL {{ ?alloy ns:gammaPrimeVolPct ?gammaPrime }}
          OPTIONAL {{ ?alloy ns:typicalHeatTreatment ?heatTreat }}
          OPTIONAL {{
            ?alloy ns:hasComposition ?comp .
            OPTIONAL {{ ?comp ns:otherConstituents ?others }}
          }}
        }}
        ORDER BY ?label
        LIMIT {page_size} OFFSET {offset}
        """

        res = query_graphdb(q)
        results = res['results']['bindings']

        if not results:
            break

        for b in results:
            alloys[b["alloy"]["value"]] = {
                "label": b["label"]["value"],
                "uns": b.get("uns", {}).get("value"),
                "family": b.get("family", {}).get("value"),
                "density": to_float(b.get("density", {}).get("value")),
                "gammaPrime": to_float(b.get("gammaPrime", {}).get("value")),
                "heatTreat": b.get("heatTreat", {}).get("value"),
                "comp": b.get("comp", {}).get("value"),
                "others": b.get("others", {}).get("value"),
                "variants": []
            }

        if len(results) < page_size:
            break
        offset += page_size

    log.info(f"Found {len(alloys)} alloys")

    # Fetch variants
    offset = 0
    while True:
        q = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX ns: <{BASE}>
        SELECT ?alloy ?variant ?variantName ?procMethod ?sourceUrl
        WHERE {{
          ?alloy rdf:type ns:NickelBasedSuperalloy ;
                 ns:hasVariant ?variant .
          OPTIONAL {{ ?variant ns:variantName ?variantName }}
          OPTIONAL {{ ?variant ns:processingMethod ?procMethod }}
          OPTIONAL {{ ?variant ns:sourceUrl ?sourceUrl }}
        }}
        LIMIT {page_size} OFFSET {offset}
        """

        try:
            res = query_graphdb(q)
            results = res['results']['bindings']

            if not results:
                break

            for b in results:
                alloy_iri = b["alloy"]["value"]
                if alloy_iri in alloys:
                    alloys[alloy_iri]["variants"].append({
                        "iri": b["variant"]["value"],
                        "name": b.get("variantName", {}).get("value") or "default",
                        "processing": b.get("procMethod", {}).get("value"),
                        "source": b.get("sourceUrl", {}).get("value")
                    })

            if len(results) < page_size:
                break
            offset += page_size
        except:
            break

    return alloys


def fetch_composition(comp_iri):
    """Get composition entries for a composition."""
    q = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ns: <{BASE}>
    SELECT ?entry ?elem ?elemLabel ?isBal ?qty ?num ?min ?max ?nom ?unit ?approx ?qual ?raw
    WHERE {{
      <{comp_iri}> ns:hasComponent ?entry .
      ?entry ns:element ?elem .
      OPTIONAL {{ ?elem rdfs:label ?elemLabel }}
      OPTIONAL {{ ?entry ns:isBalanceRemainder ?isBal }}
      OPTIONAL {{
        ?entry ns:hasMassFraction ?qty .
        OPTIONAL {{ ?qty ns:numericValue ?num }}
        OPTIONAL {{ ?qty ns:minInclusive ?min }}
        OPTIONAL {{ ?qty ns:maxInclusive ?max }}
        OPTIONAL {{ ?qty ns:nominal ?nom }}
        OPTIONAL {{ ?qty ns:unitSymbol ?unit }}
        OPTIONAL {{ ?qty ns:isApproximate ?approx }}
        OPTIONAL {{ ?qty ns:qualifier ?qual }}
        OPTIONAL {{ ?qty ns:rawString ?raw }}
      }}
    }}
    """

    res = query_graphdb(q)
    entries = {}

    for b in res["results"]["bindings"]:
        entry_iri = b["entry"]["value"]
        elem_label = b.get("elemLabel", {}).get("value")
        elem_iri = b["elem"]["value"]

        symbol = elem_label if elem_label else elem_iri.split("#")[-1].replace("Element_", "")

        qty = None
        if b.get("qty"):
            qty = {
                "iri": b["qty"]["value"],
                "numericValue": to_float(b.get("num", {}).get("value")),
                "minInclusive": to_float(b.get("min", {}).get("value")),
                "maxInclusive": to_float(b.get("max", {}).get("value")),
                "nominal": to_float(b.get("nom", {}).get("value")),
                "unitSymbol": b.get("unit", {}).get("value"),
                "isApproximate": to_bool(b.get("approx", {}).get("value")),
                "qualifier": b.get("qual", {}).get("value"),
                "rawString": b.get("raw", {}).get("value"),
            }

        entries[entry_iri] = {
            "symbol": symbol,
            "is_balance": to_bool(b.get("isBal", {}).get("value")),
            "qty": qty,
        }

    return entries


def fetch_measurements(source_iri):
    """Get measurements for an alloy or variant."""
    measurements = []

    # Try direct measurements first
    q = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ns: <{BASE}>
    SELECT ?meas ?prop ?qty ?num ?min ?max ?nom ?unit ?approx ?qual ?raw
           ?tempCat ?heatTreat ?testTemp ?testTempNum ?testTempUnit
           ?stress ?lifeHours
    WHERE {{
      <{source_iri}> ns:hasMeasurement ?meas .
      ?meas ns:measures ?prop .
      OPTIONAL {{
        ?meas ns:hasQuantity ?qty .
        OPTIONAL {{ ?qty ns:numericValue ?num }}
        OPTIONAL {{ ?qty ns:minInclusive ?min }}
        OPTIONAL {{ ?qty ns:maxInclusive ?max }}
        OPTIONAL {{ ?qty ns:nominal ?nom }}
        OPTIONAL {{ ?qty ns:unitSymbol ?unit }}
        OPTIONAL {{ ?qty ns:isApproximate ?approx }}
        OPTIONAL {{ ?qty ns:qualifier ?qual }}
        OPTIONAL {{ ?qty ns:rawString ?raw }}
      }}
      OPTIONAL {{ ?meas ns:temperatureCategory ?tempCat }}
      OPTIONAL {{ ?meas ns:heatTreatmentCondition ?heatTreat }}
      OPTIONAL {{ ?meas ns:stress ?stress }}
      OPTIONAL {{ ?meas ns:lifeHours ?lifeHours }}
      OPTIONAL {{
        ?meas ns:hasTestTemperature ?testTemp .
        OPTIONAL {{ ?testTemp ns:numericValue ?testTempNum }}
        OPTIONAL {{ ?testTemp ns:unitSymbol ?testTempUnit }}
      }}
    }}
    """

    try:
        res = query_graphdb(q)
        for b in res["results"]["bindings"]:
            prop_type = b["prop"]["value"].split("#")[-1]

            qty = None
            if b.get("qty"):
                qty = {
                    "iri": b["qty"]["value"],
                    "numericValue": to_float(b.get("num", {}).get("value")),
                    "minInclusive": to_float(b.get("min", {}).get("value")),
                    "maxInclusive": to_float(b.get("max", {}).get("value")),
                    "nominal": to_float(b.get("nom", {}).get("value")),
                    "unitSymbol": b.get("unit", {}).get("value"),
                    "isApproximate": to_bool(b.get("approx", {}).get("value")),
                    "qualifier": b.get("qual", {}).get("value"),
                    "rawString": b.get("raw", {}).get("value"),
                }

            test_temp = None
            if b.get("testTemp"):
                test_temp = {
                    "iri": b["testTemp"]["value"],
                    "numericValue": to_float(b.get("testTempNum", {}).get("value")),
                    "unitSymbol": b.get("testTempUnit", {}).get("value"),
                }

            measurements.append({
                "iri": b["meas"]["value"],
                "prop_type": prop_type,
                "qty": qty,
                "temp_cat": b.get("tempCat", {}).get("value"),
                "heat_treatment": b.get("heatTreat", {}).get("value"),
                "stress": to_float(b.get("stress", {}).get("value")),
                "life_hours": to_float(b.get("lifeHours", {}).get("value")),
                "test_temp": test_temp,
            })
    except:
        pass

    # Try PropertySet structure
    q2 = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ns: <{BASE}>
    SELECT ?propSet ?prop ?meas ?qty ?num ?min ?max ?nom ?unit ?approx ?qual ?raw
           ?tempCat ?heatTreat ?testTemp ?testTempNum ?testTempUnit
           ?stress ?lifeHours
    WHERE {{
      <{source_iri}> ns:hasPropertySet ?propSet .
      ?propSet ns:measuresProperty ?prop .
      ?propSet ns:hasMeasurement ?meas .
      OPTIONAL {{
        ?meas ns:hasQuantity ?qty .
        OPTIONAL {{ ?qty ns:numericValue ?num }}
        OPTIONAL {{ ?qty ns:minInclusive ?min }}
        OPTIONAL {{ ?qty ns:maxInclusive ?max }}
        OPTIONAL {{ ?qty ns:nominal ?nom }}
        OPTIONAL {{ ?qty ns:unitSymbol ?unit }}
        OPTIONAL {{ ?qty ns:isApproximate ?approx }}
        OPTIONAL {{ ?qty ns:qualifier ?qual }}
        OPTIONAL {{ ?qty ns:rawString ?raw }}
      }}
      OPTIONAL {{ ?meas ns:temperatureCategory ?tempCat }}
      OPTIONAL {{ ?meas ns:heatTreatmentCondition ?heatTreat }}
      OPTIONAL {{ ?meas ns:stress ?stress }}
      OPTIONAL {{ ?meas ns:lifeHours ?lifeHours }}
      OPTIONAL {{
        ?meas ns:hasTestTemperature ?testTemp .
        OPTIONAL {{ ?testTemp ns:numericValue ?testTempNum }}
        OPTIONAL {{ ?testTemp ns:unitSymbol ?testTempUnit }}
      }}
    }}
    """

    try:
        res = query_graphdb(q2)
        for b in res["results"]["bindings"]:
            prop_type = b["prop"]["value"].split("#")[-1]

            qty = None
            if b.get("qty"):
                qty = {
                    "iri": b["qty"]["value"],
                    "numericValue": to_float(b.get("num", {}).get("value")),
                    "minInclusive": to_float(b.get("min", {}).get("value")),
                    "maxInclusive": to_float(b.get("max", {}).get("value")),
                    "nominal": to_float(b.get("nom", {}).get("value")),
                    "unitSymbol": b.get("unit", {}).get("value"),
                    "isApproximate": to_bool(b.get("approx", {}).get("value")),
                    "qualifier": b.get("qual", {}).get("value"),
                    "rawString": b.get("raw", {}).get("value"),
                }

            test_temp = None
            if b.get("testTemp"):
                test_temp = {
                    "iri": b["testTemp"]["value"],
                    "numericValue": to_float(b.get("testTempNum", {}).get("value")),
                    "unitSymbol": b.get("testTempUnit", {}).get("value"),
                }

            measurements.append({
                "iri": b["meas"]["value"],
                "prop_type": prop_type,
                "qty": qty,
                "temp_cat": b.get("tempCat", {}).get("value"),
                "heat_treatment": b.get("heatTreat", {}).get("value"),
                "stress": to_float(b.get("stress", {}).get("value")),
                "life_hours": to_float(b.get("lifeHours", {}).get("value")),
                "test_temp": test_temp,
            })
    except:
        pass

    return measurements


def upsert_object(coll, uuid, props):
    """Insert or update object."""
    props = {k: v for k, v in props.items() if v is not None}
    if not props:
        props = {}

    if coll.data.exists(uuid):
        if props:
            coll.data.update(uuid=uuid, properties=props)
    else:
        coll.data.insert(uuid=uuid, properties=props)


def create_quantity(client, qty):
    """Create quantity object and return UUID."""
    if not qty:
        return None

    q_uuid = uuid5(f"Quantity:{qty['iri']}")
    props = {}

    for k in ("numericValue", "minInclusive", "maxInclusive", "nominal",
              "unitSymbol", "isApproximate", "qualifier", "rawString"):
        if qty.get(k) is not None:
            props[k] = qty[k]

    upsert_object(client.collections.get("Quantity"), q_uuid, props)
    return q_uuid


def add_reference(coll, from_uuid, ref_name, to_uuid):
    """Add reference, ignore if exists."""
    try:
        coll.data.reference_add(from_uuid, ref_name, to_uuid)
    except:
        pass


def main():
    log.info("Starting GraphDB → Weaviate import")

    alloys = fetch_alloys()
    client = connect_weaviate()

    try:
        # Get collections
        colls = {
            "alloy": client.collections.get("NickelBasedSuperalloy"),
            "variant": client.collections.get("Variant"),
            "comp": client.collections.get("Composition"),
            "entry": client.collections.get("CompositionEntry"),
            "elem": client.collections.get("Element"),
            "propset": client.collections.get("PropertySet"),
            "meas": client.collections.get("Measurement"),
            "prop": client.collections.get("MechanicalProperty"),
            "test": client.collections.get("TestCondition"),
            "route": client.collections.get("ProcessingRoute"),
        }

        # Build lookups
        elem_lookup = {
            o.properties.get("symbol"): o.uuid
            for o in colls["elem"].iterator()
            if o.properties.get("symbol")
        }

        prop_lookup = {
            o.properties.get("propertyType"): o.uuid
            for o in colls["prop"].iterator()
            if o.properties.get("propertyType")
        }

        stats = defaultdict(int)

        # Process each alloy
        log.info(f"Importing {len(alloys)} alloys...")

        for idx, (a_iri, meta) in enumerate(alloys.items(), 1):
            if idx % 50 == 0:
                log.info(f"  {idx}/{len(alloys)}...")

            a_uuid = uuid5(f"Alloy:{a_iri}")

            # Create alloy
            upsert_object(colls["alloy"], a_uuid, {
                "tradeDesignation": meta["label"],
                "unsNumber": meta.get("uns"),
                "family": meta.get("family"),
                "density": meta.get("density"),
                "gammaPrimeVolPct": meta.get("gammaPrime"),
                "typicalHeatTreatment": meta.get("heatTreat"),
            })
            stats["alloys"] += 1

            # Create composition
            if meta.get("comp"):
                comp_uuid = uuid5(f"Composition:{meta['comp']}")
                upsert_object(colls["comp"], comp_uuid, {
                    "otherConstituents": meta.get("others")
                })
                add_reference(colls["alloy"], a_uuid, "hasComposition", comp_uuid)
                stats["compositions"] += 1

                # Add composition entries
                entries = fetch_composition(meta["comp"])
                for e_iri, e in entries.items():
                    e_uuid = uuid5(f"CompEntry:{e_iri}")
                    upsert_object(colls["entry"], e_uuid, {
                        "isBalanceRemainder": e["is_balance"]
                    })
                    add_reference(colls["comp"], comp_uuid, "hasComponent", e_uuid)

                    # Link element
                    sym = e["symbol"]
                    el_uuid = elem_lookup.get(sym)
                    if not el_uuid:
                        el_uuid = uuid5(f"Element:{sym}")
                        upsert_object(colls["elem"], el_uuid, {"symbol": sym, "label": sym})
                        elem_lookup[sym] = el_uuid
                    add_reference(colls["entry"], e_uuid, "hasElement", el_uuid)

                    # Link quantity
                    if e.get("qty"):
                        q_uuid = create_quantity(client, e["qty"])
                        if q_uuid:
                            add_reference(colls["entry"], e_uuid, "hasMassFraction", q_uuid)
                            stats["quantities"] += 1

                    stats["entries"] += 1

            # Create variants
            variants = meta.get("variants") or [{
                "iri": f"{a_iri}_default",
                "name": "default",
                "processing": None,
                "source": None
            }]

            alloy_meas = fetch_measurements(a_iri)

            for var in variants:
                v_uuid = uuid5(f"Variant:{var['iri']}")
                upsert_object(colls["variant"], v_uuid, {
                    "variantName": var.get("name"),
                    "sourceUrl": var.get("source")
                })
                add_reference(colls["alloy"], a_uuid, "hasVariant", v_uuid)
                stats["variants"] += 1

                # Processing route
                if var.get("processing"):
                    pr_uuid = uuid5(f"ProcRoute:{a_iri}:{var['processing']}")
                    upsert_object(colls["route"], pr_uuid, {
                        "processingDescription": var["processing"]
                    })
                    add_reference(colls["variant"], v_uuid, "hasProcessingRoute", pr_uuid)

                # Get measurements
                if var["iri"] != f"{a_iri}_default":
                    meas = fetch_measurements(var["iri"])
                else:
                    meas = alloy_meas

                # Group by property type
                by_prop = defaultdict(list)
                for m in meas:
                    by_prop[m["prop_type"]].append(m)

                # Create property sets
                for prop_type, measurements in by_prop.items():
                    ps_uuid = uuid5(f"PropertySet:{v_uuid}:{prop_type}")
                    upsert_object(colls["propset"], ps_uuid, {})
                    add_reference(colls["variant"], v_uuid, "hasPropertySet", ps_uuid)
                    stats["property_sets"] += 1

                    # Link property
                    mp_uuid = prop_lookup.get(prop_type)
                    if mp_uuid:
                        add_reference(colls["propset"], ps_uuid, "measuresProperty", mp_uuid)

                    # Create measurements
                    for m in measurements:
                        m_uuid = uuid5(f"Measurement:{m['iri']}")
                        upsert_object(colls["meas"], m_uuid, {
                            "stress": m.get("stress"),
                            "lifeHours": m.get("life_hours")
                        })
                        add_reference(colls["propset"], ps_uuid, "hasMeasurement", m_uuid)
                        stats["measurements"] += 1

                        # Link quantity
                        if m.get("qty"):
                            q_uuid = create_quantity(client, m["qty"])
                            if q_uuid:
                                add_reference(colls["meas"], m_uuid, "hasQuantity", q_uuid)
                                stats["quantities"] += 1

                        # Test conditions
                        if m.get("temp_cat") or m.get("heat_treatment") or m.get("test_temp"):
                            tc_uuid = uuid5(f"TestCond:{m['iri']}")
                            upsert_object(colls["test"], tc_uuid, {
                                "temperatureCategory": m.get("temp_cat"),
                                "heatTreatmentCondition": m.get("heat_treatment")
                            })
                            add_reference(colls["meas"], m_uuid, "hasTestCondition", tc_uuid)
                            stats["test_conditions"] += 1

                            if m.get("test_temp"):
                                temp_q_uuid = create_quantity(client, m["test_temp"])
                                if temp_q_uuid:
                                    add_reference(colls["test"], tc_uuid, "hasTemperature", temp_q_uuid)
                                    stats["quantities"] += 1

        log.info("\nImport complete!")
        for key, value in sorted(stats.items()):
            log.info(f"  {key}: {value}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
