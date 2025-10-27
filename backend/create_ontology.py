import os
from owlready2 import (
    get_ontology, Thing, DataProperty, ObjectProperty, default_world,
    sync_reasoner_pellet, sync_reasoner,
)

BASE_IRI = "http://www.semanticweb.org/alexlecu/ontologies/nisuperalloy"
SAVE      = os.getenv("SAVE_ONTOLOGY", "1")
SAVE_FMT  = os.getenv("SAVE_FORMAT", "rdfxml")
OUT_PATH  = os.getenv("ONTO_OUT", "NiSuperAlloy_Ont_GEN.rdf")
REASONER  = os.getenv("REASONER", "hermit")

def build_ontology():
    onto = get_ontology(BASE_IRI)
    with onto:

        # ---------- Classes ----------
        class NickelBasedSuperalloy(Thing):
            pass

        class Composition(Thing):
            pass

        class CompositionEntry(Thing):
            pass

        class Element(Thing):
            pass

        class MechanicalProperty(Thing):
            pass

        class TensileStrength(MechanicalProperty):
            pass

        class YieldStrength(MechanicalProperty):
            pass

        class Elongation(MechanicalProperty):
            pass

        class Hardness(MechanicalProperty):
            pass

        class ElasticModulus(MechanicalProperty):
            pass

        class Measurement(Thing):
            pass

        class Quantity(Thing):
            pass

        # ---------- Object Properties ----------
        class hasComposition(ObjectProperty):
            domain = [NickelBasedSuperalloy]
            range  = [Composition]

        class hasComponent(ObjectProperty):
            domain = [Composition]
            range  = [CompositionEntry]

        class element(ObjectProperty):
            domain = [CompositionEntry]
            range  = [Element]

        class hasMassFraction(ObjectProperty):
            domain = [CompositionEntry]
            range  = [Quantity]

        class hasMeasurement(ObjectProperty):
            domain = [NickelBasedSuperalloy]
            range  = [Measurement]

        class measures(ObjectProperty):
            domain = [Measurement]
            range  = [MechanicalProperty]

        class hasQuantity(ObjectProperty):
            domain = [Measurement]
            range  = [Quantity]

        # ---------- Data Properties ----------
        class tradeDesignation(DataProperty):
            domain = [NickelBasedSuperalloy]
            range  = [str]

        class unsNumber(DataProperty):
            domain = [NickelBasedSuperalloy]
            range  = [str]

        # Quantity data
        class numericValue(DataProperty):
            domain = [Quantity]
            range  = [float]

        class minInclusive(DataProperty):
            domain = [Quantity]
            range  = [float]

        class maxInclusive(DataProperty):
            domain = [Quantity]
            range  = [float]

        class nominal(DataProperty):
            domain = [Quantity]
            range  = [float]

        class unitSymbol(DataProperty):
            domain = [Quantity]
            range  = [str]

        class isApproximate(DataProperty):
            domain = [Quantity]
            range  = [bool]

        # Composition helpers
        class isBalanceRemainder(DataProperty):
            domain = [CompositionEntry]
            range  = [bool]

        class otherConstituents(DataProperty):
            domain = [Composition]
            range  = [str]

        # ---------- Cardinality restrictions ----------
        # CompositionEntry: exactly 1 element; at most 1 mass fraction
        CompositionEntry.is_a.append(element.exactly(1, Element))
        CompositionEntry.is_a.append(hasMassFraction.max(1, Quantity))

        # Measurement: exactly 1 property kind; exactly 1 quantity
        Measurement.is_a.append(measures.exactly(1, MechanicalProperty))
        Measurement.is_a.append(hasQuantity.exactly(1, Quantity))

        # ---------- Ontology metadata ----------
        onto.metadata.label.append("Ni Superalloy Ontology")
        onto.metadata.comment.append(
            "Ni-based superalloy ontology using an n-ary pattern for composition and mechanical properties. "
            "Quantities support exact values, ranges, inequalities and unit/scale strings."
        )
        onto.metadata.versionInfo.append("7.0.0")

    return onto

def run_reasoner(onto):
    if REASONER.lower() == "hermit":
        try:
            with onto:
                sync_reasoner()
        except Exception:
            with onto:
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
    else:
        with onto:
            sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)

def main():
    onto = build_ontology()
    run_reasoner(onto)

    if SAVE:
        onto.save(file=OUT_PATH, format=SAVE_FMT)
        print(f"Saved ontology to {OUT_PATH} ({SAVE_FMT})")
    else:

        g = default_world.as_rdflib_graph()
        print(f"In-memory triples (asserted + inferred): {len(g)}")

if __name__ == "__main__":
    main()
