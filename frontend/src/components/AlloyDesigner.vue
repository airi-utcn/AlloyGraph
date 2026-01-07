<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { API_BASE_URL } from '../config'

// --- PROPS ---
const props = defineProps({
  initialAlloy: {
    type: Object,
    default: null
  }
})

// --- STATE ---
const mode = ref('manual') // 'manual' (Composition -> Props) or 'auto' (Props -> Composition)
const loading = ref(false)
const logs = ref([])
const result = ref(null)

// Clear results when switching modes
watch(mode, () => {
  result.value = null
  logs.value = []
})

// --- MANUAL MODE STATE ---
const manualComp = ref({ Ni: 60, Cr: 20, Al: 10, Ti: 5, Co: 5 })
const manualTemp = ref(20) // Room temperature
const manualProcessing = ref('cast')  // Processing type for Evaluate mode

// Initialize from prop if available
const initFromProp = (alloy) => {
  if (!alloy) return
  if (alloy.composition) {
    manualComp.value = { ...alloy.composition }
  }
  if (alloy.processing_method) {
    manualProcessing.value = alloy.processing_method.toLowerCase()
  }
  // Reset results when a new alloy is loaded
  result.value = null
  mode.value = 'manual'
}

// Initial check
if (props.initialAlloy) initFromProp(props.initialAlloy)

// Watch for changes (needed when component is kept alive)
watch(() => props.initialAlloy, (newVal) => {
  initFromProp(newVal)
})

const PRESETS = {
  "Waspaloy": { "Ni": 58.0, "Cr": 19.5, "Co": 13.5, "Mo": 4.3, "Ti": 3.0, "Al": 1.4, "B": 0.006, "Zr": 0.05 },
  "Inconel 718": { "Ni": 52.5, "Cr": 19.0, "Fe": 19.0, "Nb": 5.1, "Mo": 3.0, "Ti": 0.9, "Al": 0.5 },
  "Udimet 720": { "Ni": 55.0, "Cr": 16.0, "Co": 14.7, "Ti": 5.0, "Al": 2.5, "Mo": 3.0, "W": 1.25 },
  "Udimet 500": { "Ni": 54.0, "Cr": 18.0, "Co": 18.5, "Mo": 4.0, "Al": 2.9, "Ti": 2.9, "C": 0.08, "B": 0.006, "Zr": 0.05 }
}

const loadPreset = (name) => {
  manualComp.value = { ...PRESETS[name] }
  result.value = null
}

const addElement = (el) => {
  if (el && !manualComp.value[el]) {
    manualComp.value[el] = 0.0
  }
}

const removeElement = (el) => {
  delete manualComp.value[el]
}

const runValidation = async () => {
  loading.value = true
  logs.value = []
  result.value = null
  logs.value.push(`🧪 Validating Composition at ${manualTemp.value}°C (${manualProcessing.value})...`)
  
  try {
    const res = await axios.post(`${API_BASE_URL}/api/validate`, {
      composition: manualComp.value,
      temp: manualTemp.value,
      processing: manualProcessing.value
    })
    result.value = res.data.result
    logs.value.push("✅ Prediction Complete.")
  } catch (error) {
    logs.value.push("❌ Error: " + error.message)
  } finally {
    loading.value = false
  }
}

// --- AUTO MODE STATE ---
const targets = ref({
  yield: 1200,      // Realistic superalloy yield strength target
  tensile: 0,       // Optional - leave at 0
  elongation: 0,    // Optional - leave at 0
  density: 8.5,     // Realistic density target for Ni-based superalloys
  gamma_prime: 0    // Optional - leave at 0
})
const autoIterations = ref(3)
const autoTemp = ref(20)  // Room temperature
const autoProcessing = ref('cast')

const runDesign = async () => {
  loading.value = true
  logs.value = [] // Keep logs for user feedback
  result.value = null
  
  logs.value.push("🚀 Starting Inverse Design Agent...")
  let targetLog = `Targets: Yield≥${targets.value.yield} MPa`
  if (targets.value.tensile > 0) targetLog += `, Tensile≥${targets.value.tensile} MPa`
  if (targets.value.elongation > 0) targetLog += `, Elongation≥${targets.value.elongation}%`
  if (targets.value.density < 99) targetLog += `, Density≤${targets.value.density} g/cm³`
  if (targets.value.gamma_prime > 0) targetLog += `, Gamma Prime≥${targets.value.gamma_prime}%`
  logs.value.push(targetLog)

  try {
    // Build target_props object with all non-zero values
    const target_props = {
      'Yield Strength': targets.value.yield
    }
    if (targets.value.tensile > 0) target_props['Tensile Strength'] = targets.value.tensile
    if (targets.value.elongation > 0) target_props['Elongation'] = targets.value.elongation
    if (targets.value.density < 99) target_props['Density'] = targets.value.density
    if (targets.value.gamma_prime > 0) target_props['Gamma Prime'] = targets.value.gamma_prime

    const response = await axios.post(`${API_BASE_URL}/api/design`, {
      target_props: target_props, // Use the constructed target_props object
      processing: autoProcessing.value,
      temp: autoTemp.value,
      max_iter: autoIterations.value
    })
    result.value = response.data
    logs.value.push("✅ Design Complete!")
  } catch (err) {

    logs.value.push("❌ Error: " + err.message)
    result.value = { error: err.message }
  } finally {
    loading.value = false
  }
}
// Helper to parse value from potential string with units (e.g. "970.0 MPa @ 20C")
const parseVal = (v) => {
    if (typeof v === 'number') return v
    if (typeof v === 'string') {
        // Extract first number found
        const match = v.match(/[\d\.]+/)
        return match ? parseFloat(match[0]) : 0
    }
    return 0
}

// Helper to fuzzy find property (e.g. "Yield Strength" matches "Yield Strength (MPa)" or "YieldStrength")
const lookUpProp = (obj, keyPart) => {
    if (!obj) return undefined
    // Direct match
    if (obj[keyPart]) return obj[keyPart]

    // Fuzzy match keys
    const keyPartSimple = keyPart.replace(/\s+/g, '').toLowerCase() // e.g. "yieldstrength"
    const keys = Object.keys(obj)
    for (const k of keys) {
        // Normalize key k
        // e.g. "Yield Strength (MPa)" -> "yieldstrength(mpa)"
        // Check if k starts with keyPartSimple or contains it distinctly?
        // Simplest: remove spaces, lowercase, remove content in parens
        const kClean = k.replace(/\s+/g, '').toLowerCase().replace(/\(.*\)/, '')
        if (kClean === keyPartSimple) return obj[k]
        if (kClean.includes(keyPartSimple)) return obj[k]
    }
    return undefined
}

// Helper to format metric labels with human-readable names
const formatMetricLabel = (key) => {
  const labelMap = {
    'md_average': 'Md Temperature (avg)',
    'sss_wt_pct': 'Solid Solution Strengthening (wt%)',
    'tcp_risk': 'TCP Risk',
    'gamma_prime_fraction': 'γ\' Fraction',
    'lattice_misfit': 'Lattice Misfit',
    'partitioning_ni': 'Ni Partitioning',
    'partitioning_cr': 'Cr Partitioning',
    'partitioning_al': 'Al Partitioning',
    'partitioning_ti': 'Ti Partitioning'
  }
  return labelMap[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
}

const parsedResults = computed(() => {
  if (!result.value) return null
  
  // The API returns {result: {actual data}} for design mode
  let data = result.value.result || result.value
  let comp = null
  let props = {}
  let propertyIntervals = {}
  let confidence = {}
  let explanation = ""
  let auditPenalties = []
  let metallurgyMetrics = {}
  let status = "UNKNOWN"
  let tcpRisk = "UNKNOWN"
  let similar = []
  let summary = ""
  
  // CASE 1: Design Output - has composition at top level
  if (data.composition) {
    comp = data.composition
    // Design output structure: {composition: {...}, properties: {...}, explanation: ...}
    // Properties might be at top level or nested
    props = data.properties || {}
    propertyIntervals = data.property_intervals || {}
    confidence = data.confidence || {}
    explanation = data.explanation || ""
    auditPenalties = data.audit_penalties || []
    metallurgyMetrics = data.metallurgy_metrics || {}
    status = data.status || "UNKNOWN"
    tcpRisk = data.tcp_risk || "UNKNOWN"
    similar = data.similar_alloys || []
    summary = data.summary || ""
  } else {
    // CASE 2: Evaluate/Validation Output - we submitted the composition
    comp = manualComp.value
    props = data.properties || {}
    propertyIntervals = data.property_intervals || {}
    confidence = data.confidence || {}
    explanation = data.explanation || ""
    auditPenalties = data.audit_penalties || []
    metallurgyMetrics = data.metallurgy_metrics || {}
    status = data.status || "UNKNOWN"
    tcpRisk = data.tcp_risk || "UNKNOWN"
    similar = data.similar_alloys || []
    summary = data.summary || ""
  }

  // Format properties for display
  const formattedProps = [
    { label: "Yield Strength", val: parseVal(lookUpProp(props, "Yield Strength")), unit: "MPa", icon: "🏋️" },
    { label: "Tensile Strength", val: parseVal(lookUpProp(props, "Tensile Strength") || lookUpProp(props, "Ultimate Tensile Strength")), unit: "MPa", icon: "⛓️" },
    { label: "Elongation", val: parseVal(lookUpProp(props, "Elongation")), unit: "%", icon: "📏" },
    { label: "Density", val: parseVal(lookUpProp(props, "Density")), unit: "g/cm³", icon: "🧱" },
    { label: "Gamma Prime", val: parseVal(lookUpProp(props, "Gamma Prime")), unit: "%", icon: "💎" },
  ].filter(p => p.val !== undefined && p.val !== null)

  // Add interval data to each property
  formattedProps.forEach(prop => {
    const interval = propertyIntervals[prop.label] || {}
    prop.lower = interval.lower
    prop.upper = interval.upper
    prop.uncertainty = interval.uncertainty
  })

  return { 
    comp, 
    formattedProps, 
    propertyIntervals,
    confidence,
    explanation,
    auditPenalties,
    metallurgyMetrics,
    status,
    tcpRisk,
    similar, 
    summary 
  }
})

</script>

<template>
  <div class="alloy-designer">
    <!-- Modern Mode Switcher -->
    <div class="mode-switcher glass-card">
      <button 
        :class="['mode-btn', { active: mode === 'manual' }]" 
        @click="mode = 'manual'"
      >
        <span class="mode-icon">🧪</span>
        <span class="mode-label">Evaluate</span>
      </button>
      <button 
        :class="['mode-btn', { active: mode === 'auto' }]" 
        @click="mode = 'auto'"
      >
        <span class="mode-icon">🧬</span>
        <span class="mode-label">Design</span>
      </button>
    </div>

    <!-- MANUAL MODE: EVALUATE COMPOSITION -->
    <div v-if="mode === 'manual'" class="panel glass-card">
      <h3>Define Alloy Composition</h3>
      <p class="helper-text">Enter element percentages (should sum to ~100%). Use presets or add custom elements.</p>
      
      <!-- Quick Presets -->
      <div class="presets-section">
        <label class="section-label">Quick Start:</label>
        <div class="preset-buttons">
          <button v-for="(comp, name) in PRESETS" :key="name" @click="loadPreset(name)" class="preset-btn">
            {{ name }}
          </button>
        </div>
      </div>
      
      <!-- Composition Grid -->
      <div class="section-label">Composition (wt%):</div>
      <div class="comp-grid">
        <div v-for="(val, el) in manualComp" :key="el" class="element-box">
          <label>{{ el }}</label>
          <input type="number" v-model.number="manualComp[el]" step="0.1" />
          <span class="remove" @click="removeElement(el)">×</span>
        </div>
        <div class="add-box">
          <input type="text" placeholder="+ Add Element" @keyup.enter="addElement($event.target.value); $event.target.value=''" class="add-input" />
        </div>
      </div>

      <!-- Bottom Actions -->
      <div class="eval-controls">
        <div class="temp-inline">
          <label>Temperature:</label>
          <input type="number" v-model.number="manualTemp" class="temp-simple" />
          <span class="temp-unit">°C</span>
          
          <label style="margin-left: var(--space-lg);">Processing:</label>
          <select v-model="manualProcessing" class="temp-simple" style="width: 100px">
            <option value="cast">Cast</option>
            <option value="wrought">Wrought</option>
          </select>
        </div>
        
        <button @click="runValidation" :disabled="loading" class="primary-btn">
          {{ loading ? 'Running Models...' : '▶ Predict Properties' }}
        </button>
      </div>
    </div>

    <!-- AUTO MODE: ALLOY DESIGN -->
    <div v-if="mode === 'auto'" class="panel glass-card">
      <h3>Define Target Properties</h3>
      <p class="helper-text">Specify target values for desired properties. Set to 0 to skip any property.</p>
      
      <div class="target-grid">
        <!-- Yield Strength -->
        <div class="field">
          <label>Min Yield Strength <span class="default-hint">(MPa)</span></label>
          <input v-model.number="targets.yield" type="number" placeholder="1200" />
        </div>

        <!-- Tensile Strength -->
        <div class="field">
          <label>Min Tensile Strength <span class="default-hint">(MPa)</span></label>
          <input v-model.number="targets.tensile" type="number" placeholder="0" />
        </div>

        <!-- Elongation -->
        <div class="field">
          <label>Min Elongation <span class="default-hint">(%)</span></label>
          <input v-model.number="targets.elongation" type="number" step="0.1" placeholder="0" />
        </div>

        <!-- Density -->
        <div class="field">
          <label>Max Density <span class="default-hint">(g/cm³)</span></label>
          <input v-model.number="targets.density" type="number" step="0.1" placeholder="8.5" />
        </div>

        <!-- Gamma Prime -->
        <div class="field">
          <label>Min Gamma Prime <span class="default-hint">(vol%)</span></label>
          <input v-model.number="targets.gamma_prime" type="number" step="0.1" placeholder="0" />
        </div>
      </div>

      <!-- Bottom Controls -->
      <div class="design-controls">
        <div class="control-row">
          <div class="inline-control">
            <label>Temperature:</label>
            <input type="number" v-model.number="autoTemp" class="small-input" />
            <span class="unit">°C</span>
          </div>
          
          <div class="inline-control">
            <label>Processing:</label>
            <select v-model="autoProcessing" class="small-select">
              <option value="cast">Cast</option>
              <option value="wrought">Wrought</option>
            </select>
          </div>
          
          <div class="inline-control">
            <label>Max Iterations:</label>
            <input type="number" v-model.number="autoIterations" min="1" max="10" class="small-input" style="width: 60px" />
          </div>
        </div>
        
        <button @click="runDesign" :disabled="loading" class="primary-btn magic-btn">
          {{ loading ? 'Inventing Alloy...' : '✨ Auto-Design Alloy' }}
        </button>
      </div>
    </div>

    <!-- OUTPUT RESULTS DASHBOARD -->
    <div class="output-area">
      <div v-if="loading" class="loading-state">
         <div class="spinner">⚙️ Agents are working...</div>
         <div class="logs-scroll">
            <div v-for="(log, i) in logs" :key="i" class="log-line">{{ log }}</div>
         </div>
      </div>

      <div v-if="parsedResults" class="results-dashboard animate-in">
        <div class="dashboard-header">
           <h3>🎉 Analysis Complete at {{ result.temp || manualTemp }}°C</h3>
           <p class="summary-text">{{ parsedResults.summary }}</p>
        </div>

        <!-- STATUS BADGE (only for Evaluate mode) -->
        <div v-if="mode === 'manual'" class="status-badge" :class="parsedResults.status.toLowerCase()">
          {{ parsedResults.status === 'PASS' ? '✅ PASS' : parsedResults.status === 'REJECT' ? '⚠️ REJECT' : '❌ FAIL' }}
        </div>

        <!-- 1. COMPOSITION FIRST (for Design mode) -->
        <div v-if="parsedResults.comp && mode === 'auto'" class="final-comp-section">
             <h4>🧬 Suggested Composition</h4>
             <div class="mini-comp-grid">
                <span v-for="(v, k) in parsedResults.comp" :key="k" class="mini-comp-tag">
                   <b>{{ k }}</b>: {{ v }}%
                </span>
             </div>
        </div>

        <!-- 2. PROPERTIES CARDS WITH INTERVALS -->
        <div class="props-grid">
            <div v-for="prop in parsedResults.formattedProps" :key="prop.label" class="prop-card">
               <div class="prop-icon">{{ prop.icon }}</div>
               <div class="prop-info">
                  <div class="prop-val">{{ Number(prop.val).toFixed(1) }} <small>{{ prop.unit }}</small></div>
                  <div class="prop-label">{{ prop.label }}</div>
                  <!-- INTERVAL DISPLAY -->
                  <div v-if="prop.lower && prop.upper" class="prop-interval">
                    [{{ Number(prop.lower).toFixed(0) }} - {{ Number(prop.upper).toFixed(0) }} {{ prop.unit }}]
                  </div>
                  <div v-if="prop.uncertainty" class="prop-uncertainty">
                    ±{{ Number(prop.uncertainty).toFixed(1) }} {{ prop.unit }}
                  </div>
               </div>
            </div>
        </div>

        <!-- 3. METALLURGICAL ANALYSIS -->
        <div v-if="parsedResults.explanation" class="explanation-panel">
          <div class="panel-header">💬 Metallurgical Analysis</div>
          <div class="explanation-text">{{ parsedResults.explanation }}</div>
        </div>

        <!-- 4. PHYSICS AUDIT PANEL -->
        <div v-if="parsedResults.auditPenalties.length > 0" class="audit-panel">
          <div class="panel-header">
            ⚠️ Physics Audit: {{ parsedResults.auditPenalties.length }} Penalty(ies)
          </div>
          <div class="audit-list">
            <div v-for="(penalty, i) in parsedResults.auditPenalties" :key="i" class="audit-item">
              <strong>{{ penalty.name }}</strong> ({{ penalty.value }}): {{ penalty.reason }}
            </div>
          </div>
        </div>

        <!-- SIMILAR ALLOYS -->
        <div v-if="parsedResults.similar.length" class="similar-section">
           <h4>🔍 Similar Known Alloys</h4>
           <div class="similar-list">
              <div v-for="alloy in parsedResults.similar" :key="alloy.name" class="similar-item">
                 <strong>{{ alloy.name }}</strong>
                 <span v-if="alloy.similarity" class="similarity-badge">{{ alloy.similarity }}</span>
                 <p class="similar-notes">{{ alloy.notes || JSON.stringify(alloy) }}</p>
              </div>
           </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>




.panel {
  background: #252526;
  padding: 1.5rem;
  border-radius: 8px;
}

/* === SECTION LABELS === */
.section-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: var(--space-sm);
  display: block;
}

/* === PRESETS SECTION === */
.presets-section {
  margin-bottom: var(--space-lg);
  padding: var(--space-md);
  background: rgba(255, 255, 255, 0.02);
  border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.preset-buttons {
  display: flex;
  gap: var(--space-sm);
  flex-wrap: wrap;
  margin-top: var(--space-sm);
}

.preset-btn {
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-glass);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  cursor: pointer;
  transition: all var(--transition-base);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}

.preset-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-1px);
}

/* === EVAL CONTROLS === */
.eval-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-lg);
  margin-top: var(--space-xl);
  padding-top: var(--space-lg);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.temp-inline {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.temp-simple {
  width: 80px;
  background: var(--bg-glass);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--font-size-sm);
}

.temp-inline .temp-unit {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}





.comp-grid, .target-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 10px;
  margin-bottom: 1.5rem;
}

.element-box, .field {
  background: #1e1e1e;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid #333;
  position: relative;
}
.element-box label, .field label {
  display: block;
  font-size: 0.8rem;
  color: #aaa;
  margin-bottom: 4px;
}
.element-box input, .field input {
  width: 100%;
  background: transparent;
  border: none;
  color: white;
  font-size: 1.1rem;
  font-weight: bold;
}
.remove {
  position: absolute;
  top: 2px;
  right: 6px;
  color: #555;
  cursor: pointer;
}
.remove:hover { color: red; }

.add-input {
  width: 100%;
  height: 100%;
  background: #1e1e1e;
  border: 1px dashed #555;
  color: #fff;
  text-align: center;
  border-radius: 6px;
}



.primary-btn {
  background: #007bff;
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 6px;
  font-size: 1rem;
  font-weight: bold;
  cursor: pointer;
  transition: transform 0.1s;
}
.primary-btn:hover { background: #0056b3; transform: scale(1.02); }
.primary-btn:disabled { background: #444; cursor: not-allowed; }

.magic-btn {
  background: linear-gradient(135deg, #6610f2, #d63384);
}

/* OUTPUT DASHBOARD STYLES */
.output-area {
  background: #111;
  padding: 1.5rem;
  border-radius: 12px;
  flex: 1;
  min-height: 300px;
  border: 1px solid #333;
}

.loading-state {
  text-align: center;
  padding: 2rem;
}
.spinner { 
  font-size: 1.5rem; 
  color: #ffd700; 
  margin-bottom: 1rem;
  animation: pulse 1s infinite;
}
@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }

.logs-scroll {
  max-height: 150px;
  overflow-y: auto;
  text-align: left;
  font-family: monospace;
  font-size: 0.8rem;
  color: #666;
  border-top: 1px solid #222;
  padding-top: 10px;
}

.results-dashboard {
  color: #fff;
}
.dashboard-header {
  border-bottom: 1px solid #333;
  padding-bottom: 1rem;
  margin-bottom: 1.5rem;
}
.summary-text {
  font-style: italic;
  color: #aaa;
  margin-top: 0.5rem;
  font-size: 1.1rem;
  line-height: 1.4;
}

.props-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}
.prop-card {
  background: #222;
  padding: 1rem;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 1rem;
  border: 1px solid #333;
}
.mode-icon {
  font-size: 1.5rem;
}

.mode-label {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
}

/* === MODERN MODE SWITCHER === */
.mode-switcher {
  display: flex;
  flex-direction: row;
  gap: var(--space-md);
  padding: var(--space-sm);
  margin-bottom: var(--space-xl);
}

/* === HELPER TEXT === */
.helper-text {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-md);
  line-height: 1.5;
}

/* === REQUIRED/OPTIONAL INDICATORS === */
.required {
  color: var(--danger);
  font-weight: var(--font-weight-bold);
  margin-right: var(--space-xs);
}

.optional {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-style: italic;
  margin-right: var(--space-xs);
}

/* === DEFAULT HINTS === */
.default-hint {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-normal);
  font-style: italic;
}

/* === DESIGN CONTROLS === */
.design-controls {
  margin-top: var(--space-xl);
  padding-top: var(--space-lg);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.control-row {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  flex-wrap: wrap;
}

.inline-control {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.small-input, .small-select {
  width: 100px;
  background: var(--bg-glass);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--font-size-sm);
}

.inline-control .unit {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

/* === RANGE VALUE DISPLAY === */
.range-value {
  display: inline-block;
  min-width: 2rem;
  text-align: center;
  color: var(--primary);
  font-weight: var(--font-weight-semibold);
  margin-left: var(--space-sm);
}
.prop-icon { font-size: 2rem; }
.prop-val { font-size: 1.4rem; font-weight: bold; color: #00d4ff; }
.prop-val small { font-size: 0.8rem; color: #666; font-weight: normal; }
.prop-label { font-size: 0.9rem; color: #888; }
.prop-interval {
  font-size: 0.75rem;
  color: #999;
  margin-top: 4px;
}
.prop-uncertainty {
  font-size: 0.7rem;
  color: #aaa;
  font-style: italic;
}

/* Status Badge */
.status-badge {
  display: inline-block;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-weight: bold;
  font-size: 1rem;
  margin-bottom: 1.5rem;
}
.status-badge.pass {
  background: #28a745;
  color: white;
}
.status-badge.reject {
  background: #ffc107;
  color: #333;
}
.status-badge.fail {
  background: #dc3545;
  color: white;
}

/* Panels */
.confidence-panel,
.explanation-panel,
.audit-panel,
.metrics-panel {
  background: #2a2a2a;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.5rem;
  border-left: 3px solid #007bff;
}
.panel-header {
  font-size: 1rem;
  font-weight: bold;
  color: #00d4ff;
  margin-bottom: 0.75rem;
}
.confidence-details {
  font-size: 0.9rem;
  color: #ccc;
  line-height: 1.6;
}
.explanation-text {
  font-size: 0.95rem;
  color: #ddd;
  line-height: 1.7;
  white-space: pre-wrap;
}
.mode-btn {
  flex: 1;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: 12px 24px;
  background: var(--bg-glass);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-lg);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
  position: relative;
  font-family: var(--font-family);
  font-size: var(--font-size-md);
}

.mode-btn:hover:not(.active) {
  border-color: rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.05);
  transform: translateY(-2px);
}

.mode-btn.active {
  background: linear-gradient(135deg, var(--primary), var(--secondary));
  border-color: transparent;
  color: white;
  box-shadow: var(--shadow-glow);
}
.audit-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.audit-item {
  background: #1e1e1e;
  padding: 0.6rem;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #ccc;
  border-left: 2px solid #ffc107;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.5rem;
}
.metric-item {
  background: #1e1e1e;
  padding: 0.5rem;
  border-radius: 4px;
  font-size: 0.85rem;
}
.metric-label {
  color: #888;
  margin-right: 0.5rem;
}
.metric-value {
  color: #00d4ff;
  font-weight: bold;
}

.final-comp-section {
  background: #2a2a2a;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 2rem;
}
.mini-comp-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0.5rem;
}
.mini-comp-tag {
  background: #111;
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid #444;
  font-family: monospace;
}

.similar-item {
  background: #1e1e1e;
  padding: 10px;
  border-radius: 6px;
  margin-bottom: 8px;
  border-left: 3px solid #666;
}
.similar-notes {
  font-size: 0.8rem;
  color: #888;
  margin-top: 4px;
}
</style>
