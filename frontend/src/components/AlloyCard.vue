<script setup>
import { computed } from 'vue'

const props = defineProps({
  alloy: {
    type: Object,
    required: true
  }
})

defineEmits(['design'])


// Sort composition by value
const sortedComposition = computed(() => {
  if (!props.alloy.composition) return []
  return Object.entries(props.alloy.composition)
    .sort(([, a], [, b]) => b - a)
})

const keyProperties = computed(() => {
  const propsList = []
  
  // Physical / Microstructural
  if (props.alloy.density_gcm3) propsList.push({ label: 'Density', value: `${props.alloy.density_gcm3.toFixed(2)} g/cm³`, temp: null })
  if (props.alloy.gamma_prime_vol_pct) propsList.push({ label: 'Gamma Prime', value: `${props.alloy.gamma_prime_vol_pct.toFixed(1)} vol%`, temp: null })
  
  // Mechanical Properties (YS, UTS, Elongation)
  if (props.alloy.properties && props.alloy.properties.length > 0) {
    // Helper to normalize temperature (group 20-25 as "Room Temp")
    const getTempKey = (t) => {
      if (t === null || t === undefined) return 'unknown'
      if (t >= 20 && t <= 25) return 'room'
      return t.toString()
    }

    // 1. Group all properties by temperature
    const tempGroups = {}
    
    props.alloy.properties.forEach(p => {
      if (!p.property_type) return
      const type = p.property_type.toLowerCase()
      const tempKey = getTempKey(p.temperature_c)
      
      if (!tempGroups[tempKey]) tempGroups[tempKey] = { count: 0, temp: p.temperature_c }
      const group = tempGroups[tempKey]
      
      // Identify property type
      if (type.includes('yield') || type.includes('0.2%') || type.includes('ys')) {
        group.ys = p
        group.count++
      } else if (type.includes('ultimate') || type.includes('tensile') || type.includes('uts')) {
        group.uts = p
        group.count++
      } else if ((type.includes('elongation') || type.includes('ductility')) && !type.includes('modulus')) {
        group.el = p
        group.count++
      } else if (type.includes('elastic') || type.includes('modulus') || type.includes("young's")) {
        group.modulus = p
        group.count++
      }
    })

    // 2. Score groups to find the "best" one
    // Preference: Room Temp > Most Complete > Higher Temp associated with superalloys (e.g. 600-1000C)
    let bestKey = 'unknown'
    let bestScore = -1

    Object.keys(tempGroups).forEach(key => {
      const g = tempGroups[key]
      let score = g.count * 10 
      
      // Bonus for Room Temperature
      if (key === 'room') score += 50
      
      // Tie-breaker: prefer standard service temps if data count is same
      if (key !== 'room' && key !== 'unknown') {
         // rough heuristic: specific high temps might be relevant, but room is usually baseline
         score += 1 
      }

      if (score > bestScore) {
        bestScore = score
        bestKey = key
      }
    })

    const bestSet = tempGroups[bestKey] || {}
    const roomSet = tempGroups['room'] || {}

    // 3. Construct Final List (Fall back to Room Temp or any available if missing from best set)
    const getBestProp = (type) => {
      // 1. Try best set
      if (bestSet[type]) return bestSet[type]
      // 2. Try room set (if best wasn't room)
      if (roomSet[type]) return roomSet[type]
      // 3. Fallback: find ANY
      return props.alloy.properties.find(p => {
         const t = p.property_type.toLowerCase()
         if (type === 'ys') return t.includes('yield') || t.includes('0.2%') || t.includes('ys')
         if (type === 'uts') return t.includes('ultimate') || t.includes('tensile') || t.includes('uts')
         if (type === 'el') return (t.includes('elongation') || t.includes('ductility')) && !t.includes('modulus')
         if (type === 'modulus') return t.includes('elastic') || t.includes('modulus') || t.includes("young's")
      })
    }

    const ys = getBestProp('ys')
    const uts = getBestProp('uts')
    const el = getBestProp('el')
    const em = getBestProp('modulus')

    // Add to list
    if (ys && ys.value) propsList.push({ label: 'Yield Strength', value: `${ys.value.toFixed(0)} ${ys.unit || 'MPa'}`, temp: ys.temperature_c })
    if (uts && uts.value) propsList.push({ label: 'UTS', value: `${uts.value.toFixed(0)} ${uts.unit || 'MPa'}`, temp: uts.temperature_c })
    if (el && el.value) propsList.push({ label: 'Elongation', value: `${el.value.toFixed(1)} ${el.unit || '%'}`, temp: el.temperature_c })
    if (em && em.value) propsList.push({ label: 'Elastic Modulus', value: `${em.value.toFixed(0)} ${em.unit || 'GPa'}`, temp: em.temperature_c })
  }
  
  return propsList
})
</script>

<template>
  <div class="alloy-card glass-card">
    <div class="card-header">
      <div class="title-group">
        <h3>{{ alloy.name }}</h3>
        <span class="badge">{{ alloy.processing_method }}</span>
      </div>
      <button @click="$emit('design', alloy)" class="design-btn" title="Design a variant based on this alloy">
        🧬 Design Variant
      </button>
    </div>

    <div class="card-body">
      <!-- Composition Section -->
      <div class="section">
        <h4>Composition (wt%)</h4>
        <div class="composition-grid">
          <div v-for="([el, val]) in sortedComposition" :key="el" class="element-tag">
            <span class="element">{{ el }}</span>
            <span class="value">{{ val }}%</span>
          </div>
        </div>
      </div>

      <!-- Properties Section -->
      <div class="section">
        <h4>Key Properties</h4>
        <div class="properties-grid">
          <div v-for="prop in keyProperties" :key="prop.label" class="property-item">
            <span class="label">{{ prop.label }}</span>
            <div class="value-group">
              <span class="value">{{ prop.value }}</span>
              <span v-if="prop.temp !== null && prop.temp !== undefined" class="temp">@ {{ prop.temp }}°C</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.alloy-card {
  margin-top: 0.75rem;
  padding: 0.85rem;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
}

.alloy-card:hover {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding-bottom: 0.5rem;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 1.1rem;
  color: var(--primary-light);
  font-weight: 600;
}

.badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 999px;
  color: var(--text-secondary);
  text-transform: capitalize;
  letter-spacing: 0.02em;
}

.design-btn {
  background: linear-gradient(135deg, var(--secondary) 0%, #8b5cf6 100%);
  color: white;
  border: none;
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.design-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
  filter: brightness(1.1);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

h4 {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0 0 0.35rem 0;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
}

.composition-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.element-tag {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  background: rgba(0, 0, 0, 0.25);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.8rem;
}

.element {
  font-weight: 700;
  color: var(--primary-hover);
}

.properties-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 0.5rem;
}

.property-item {
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.03);
  padding: 0.4rem 0.5rem;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.02);
}

.property-item .label {
  font-size: 0.65rem;
  color: var(--text-muted);
  margin-bottom: 2px;
  text-transform: uppercase;
}

.property-item .value {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
}

.property-item .value-group {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
}

.property-item .temp {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5); 
  font-weight: 400;
}

</style>
