import os
import json
from typing import Optional
from dataclasses import dataclass
import weaviate
from weaviate.classes.query import QueryReference


@dataclass
class PropertyMeasurement:
    """A single property measurement with value, unit, and temperature."""
    property_type: str
    value: float
    unit: str
    temperature_c: Optional[float] = None
    stress_mpa: Optional[float] = None
    life_hours: Optional[float] = None
    
    def format(self) -> str:
        """Format for display."""
        temp_str = f" @ {self.temperature_c}°C" if self.temperature_c is not None else ""
        
        if self.stress_mpa and self.life_hours:
            return f"Stress: {self.stress_mpa:.0f} MPa, Life: {self.life_hours:.0f}h{temp_str}"
        
        return f"{self.value:.0f} {self.unit}{temp_str}"


@dataclass
class AlloyData:
    """Complete alloy data from Weaviate."""
    name: str
    processing_method: str
    composition: Optional[dict[str, float]] = None
    atomic_composition: Optional[dict[str, float]] = None
    density_gcm3: Optional[float] = None
    gamma_prime_vol_pct: Optional[float] = None
    md_avg_c: Optional[float] = None
    tcp_risk: Optional[str] = None
    sss_wt_pct: Optional[float] = None
    refractory_wt_pct: Optional[float] = None
    gp_formers_wt_pct: Optional[float] = None
    properties: Optional[list[PropertyMeasurement]] = None
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = []
        if self.composition is None:
            self.composition = {}
        if self.atomic_composition is None:
            self.atomic_composition = {}


class AlloyRetriever:
    """Clean interface to Weaviate Variant collection."""
    
    def __init__(self):
        """Initialize Weaviate client."""
        self.host = os.getenv('WEAVIATE_HOST', 'localhost')
        self.port = int(os.getenv('WEAVIATE_PORT', 8081))
        self.grpc_port = int(os.getenv('WEAVIATE_GRPC_PORT', 50052))
        self._client = None
    
    def _get_client(self) -> weaviate.WeaviateClient:
        """Get or create Weaviate client."""
        if self._client is None:
            self._client = weaviate.connect_to_local(
                host=self.host,
                port=self.port,
                grpc_port=self.grpc_port
            )
        return self._client
    
    def close(self):
        """Close Weaviate connection."""
        if self._client:
            self._client.close()
            self._client = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def search_alloys(self, query: str, limit: int = 5) -> list[AlloyData]:
        """
        Search for alloys using hybrid search.

        Args:
            query: Natural language search query
            limit: Maximum number of results

        Returns:
            List of AlloyData objects with properties and temperatures
        """
        client = self._get_client()
        
        if not client.is_live():
            raise ConnectionError("Weaviate instance is not reachable")
        
        collection = client.collections.get("Variant")
        
        # Hybrid search with full property data
        response = collection.query.hybrid(
            query=query,
            limit=limit,
            return_properties=[
                "name", "processingMethod", "densityCalculated", "gammaPrimeEstimate",
                "mdAverage", "tcpRisk", "atomicCompositionJson",
                "sssTotalWtPct", "refractoryTotalWtPct", "gpFormersWtPct"
            ],
            return_references=[
                QueryReference(
                    link_on="hasComposition",
                    return_references=[
                        QueryReference(
                            link_on="hasComponent",
                            return_references=[
                                QueryReference(link_on="hasElement", return_properties=["symbol"]),
                                QueryReference(link_on="hasMassFraction", return_properties=["numericValue", "nominal"])
                            ]
                        )
                    ]
                ),
                QueryReference(
                    link_on="hasPropertySet",
                    return_references=[
                        QueryReference(
                            link_on="measuresProperty",
                            return_properties=["propertyType"]
                        ),
                        QueryReference(
                            link_on="hasMeasurement",
                            return_properties=["stress", "lifeHours"],
                            return_references=[
                                QueryReference(
                                    link_on="hasQuantity",
                                    return_properties=["numericValue", "unitSymbol"]
                                ),
                                QueryReference(
                                    link_on="hasTestCondition",
                                    return_references=[
                                        QueryReference(
                                            link_on="hasTemperature",
                                            return_properties=["numericValue"]
                                        )
                                    ]
                                )
                            ]
                        )
                    ]
                )
            ]
        )
        
        # Parse results
        alloys = []
        for obj in response.objects:
            props = obj.properties
            
            alloy = AlloyData(
                name=str(props.get('name', 'Unknown')),
                processing_method=str(props.get('processingMethod', 'Unknown')),
                density_gcm3=props.get('densityCalculated'),
                gamma_prime_vol_pct=props.get('gammaPrimeEstimate'),
                md_avg_c=props.get('mdAverage'),
                tcp_risk=props.get('tcpRisk'),
                sss_wt_pct=props.get('sssTotalWtPct'),
                refractory_wt_pct=props.get('refractoryTotalWtPct'),
                gp_formers_wt_pct=props.get('gpFormersWtPct'),
                composition={},
                atomic_composition={},
                properties=[]
            )
            
            try:
                ac_json = props.get('atomicCompositionJson')
                if ac_json:
                     data = json.loads(ac_json)
                     if "atomic_percent" in data:
                         alloy.atomic_composition = data["atomic_percent"]
                     else:
                         alloy.atomic_composition = data
            except Exception:
                pass
            
            # Extract composition
            if obj.references and "hasComposition" in obj.references:
                comp_obj = obj.references["hasComposition"].objects[0]
                if comp_obj.references and "hasComponent" in comp_obj.references:
                    for component in comp_obj.references["hasComponent"].objects:
                        if component.references and "hasElement" in component.references:
                            element_symbol = component.references["hasElement"].objects[0].properties.get("symbol")
                            if component.references and "hasMassFraction" in component.references:
                                mass_frac = component.references["hasMassFraction"].objects[0]
                                value = mass_frac.properties.get("numericValue") or mass_frac.properties.get("nominal")
                                if element_symbol and value is not None:
                                    alloy.composition[element_symbol] = float(value)
            
            # Extract properties with temperatures
            if obj.references and "hasPropertySet" in obj.references:
                for pset in obj.references["hasPropertySet"].objects:
                    prop_type = "Unknown"
                    if pset.references and "measuresProperty" in pset.references:
                        prop_type = pset.references["measuresProperty"].objects[0].properties.get("propertyType", "Unknown")
                    
                    if pset.references and "hasMeasurement" in pset.references:
                        for meas in pset.references["hasMeasurement"].objects:
                            val = 0.0
                            unit = ""
                            temp_c = None
                            stress = meas.properties.get("stress")
                            life_hours = meas.properties.get("lifeHours")
                            
                            # Get value and unit
                            if life_hours is not None:
                                val = life_hours
                                unit = "h"
                            elif meas.references and "hasQuantity" in meas.references:
                                quant = meas.references["hasQuantity"].objects[0]
                                val = quant.properties.get("numericValue", 0.0)
                                unit = quant.properties.get("unitSymbol", "")
                            
                            # Get temperature
                            if meas.references and "hasTestCondition" in meas.references:
                                tc = meas.references["hasTestCondition"].objects[0]
                                if tc.references and "hasTemperature" in tc.references:
                                    temp_c = tc.references["hasTemperature"].objects[0].properties.get("numericValue")
                            
                            alloy.properties.append(PropertyMeasurement(
                                property_type=prop_type,
                                value=val,
                                unit=unit,
                                temperature_c=temp_c,
                                stress_mpa=stress,
                                life_hours=life_hours
                            ))
            
            alloys.append(alloy)
        
        return alloys
    
    def get_alloys_with_property(self, property_name_part: str, limit: int = 50) -> list[AlloyData]:
        """
        Fetch a larger set of alloys that likely contain the requested property data.
        This is optimized for analytical queries where we do sorting in Python.
        """
        return self.search_alloys(property_name_part, limit=limit)

    @staticmethod
    def format_for_llm(alloys: list[AlloyData]) -> str:
        """
        Format alloy data for LLM consumption.

        Args:
            alloys: List of AlloyData objects

        Returns:
            Formatted string with all alloy information
        """
        if not alloys:
            return "No matching alloys found in the knowledge graph."
        
        results = []
        for alloy in alloys:
            lines = [
                f"\n{'='*70}",
                f"Alloy: {alloy.name}",
                f"Processing: {alloy.processing_method}",
                f"{'='*70}"
            ]
            
            if alloy.composition:
                lines.append("\nComposition (wt%):")
                sorted_comp = sorted(alloy.composition.items(), key=lambda x: x[1], reverse=True)
                for element, value in sorted_comp:
                    lines.append(f"  {element}: {value:.2f}%")
            
            if alloy.atomic_composition:
                lines.append("\nAtomic Composition (at%):")
                sorted_at = sorted(alloy.atomic_composition.items(), key=lambda x: x[1], reverse=True)
                for element, value in sorted_at:
                    lines.append(f"  {element}: {value:.2f}%")
            
            if alloy.density_gcm3:
                lines.append(f"\nDensity: {alloy.density_gcm3:.2f} g/cm³")
            if alloy.gamma_prime_vol_pct:
                lines.append(f"Gamma Prime: {alloy.gamma_prime_vol_pct:.1f} vol%")
            if alloy.md_avg_c:
                lines.append(f"Md (avg): {alloy.md_avg_c:.1f}°C")
            if alloy.tcp_risk:
                lines.append(f"TCP Risk: {alloy.tcp_risk}")
            if alloy.sss_wt_pct:
                lines.append(f"SSS Content: {alloy.sss_wt_pct:.1f} wt%")
            if alloy.refractory_wt_pct:
                lines.append(f"Refractory Content: {alloy.refractory_wt_pct:.1f} wt%")
            if alloy.gp_formers_wt_pct:
                lines.append(f"Gamma Prime Formers: {alloy.gp_formers_wt_pct:.1f} wt%")
            
            if alloy.properties:
                lines.append("\nMechanical Properties:")
                
                # Group by property type
                prop_groups: dict[str, list[PropertyMeasurement]] = {}
                for prop in alloy.properties:
                    if prop.property_type not in prop_groups:
                        prop_groups[prop.property_type] = []
                    prop_groups[prop.property_type].append(prop)
                
                for prop_type, measurements in prop_groups.items():
                    lines.append(f"  {prop_type}:")
                    for m in measurements:
                        lines.append(f"    • {m.format()}")
            
            results.append("\n".join(lines))
        
        return "\n\n".join(results)
