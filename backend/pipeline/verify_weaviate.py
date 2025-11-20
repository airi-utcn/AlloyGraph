import weaviate
import json
from weaviate.classes.query import Filter

def verify():
    client = weaviate.connect_to_local(port=8081, grpc_port=50052)
    
    try:
        print("Checking NickelBasedSuperalloy for new properties...")
        alloys = client.collections.get("NickelBasedSuperalloy")
        # Fetch an alloy that should have family data
        r = alloys.query.fetch_objects(
            limit=1,
            return_properties=["tradeDesignation", "family", "density", "gammaPrimeVolPct", "typicalHeatTreatment"]
        )
        
        if r.objects:
            print(f"Found Alloy: {r.objects[0].properties['tradeDesignation']}")
            print(f"  - Family: {r.objects[0].properties.get('family')}")
            print(f"  - Density: {r.objects[0].properties.get('density')}")
            print(f"  - Gamma Prime: {r.objects[0].properties.get('gammaPrimeVolPct')}")
        else:
            print("No alloys found!")

        print("\nChecking Measurement for Creep Rupture properties...")
        measurements = client.collections.get("Measurement")
        # Fetch a measurement that has stress (Creep Rupture)
        r = measurements.query.fetch_objects(
            limit=1,
            filters=Filter.by_property("stress").greater_than(0),
            return_properties=["stress", "lifeHours"]
        )
        
        if r.objects:
            print("Found Measurement with Stress:")
            print(f"  - Stress: {r.objects[0].properties.get('stress')}")
            print(f"  - Life Hours: {r.objects[0].properties.get('lifeHours')}")
        else:
            print("No measurements with stress found (might be expected if no creep data in sample, but let's check).")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    verify()
