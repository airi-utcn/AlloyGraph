# AlloyMind Designer CLI

Automated Ni-based Superalloy Discovery Engine

---

## 🚀 Quick Start

```bash
cd backend
source .venv/bin/activate

# Design a 750 MPa alloy at 900°C
python -m alloy_crew.design --yield_strength 750 --temperature 900

# High-strength wrought alloy
python -m alloy_crew.design --yield_strength 1200 --processing wrought

# Lightweight alloy
python -m alloy_crew.design --yield_strength 700 --density 8.0
```

---

## 📋 Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--yield_strength` | 1000.0 | Minimum Yield Strength (MPa) |
| `--density` | 9.0 | Maximum Density (g/cm³) |
| `--temperature` | 900.0 | Service temperature (°C) |
| `--processing` | cast | `cast` or `wrought` |
| `--iterations` | 3 | Max iterations (1-5) |
| `--composition` | None | Starting composition (JSON) |

---

## 💡 Examples

**Room Temperature Design:**
```bash
python -m alloy_crew.design --yield_strength 800 --temperature 20
```

**Quick Prototype (1 iteration):**
```bash
python -m alloy_crew.design --yield_strength 700 --iterations 1
```

**Start from Known Composition:**
```bash
python -m alloy_crew.design \
  --yield_strength 900 \
  --composition '{"Ni": 60, "Cr": 15, "Al": 4.5, "Ti": 2.5}'
```

---

## 🎯 Tips

- **Easier targets:** 500-800 MPa converge faster
- **Wrought processing:** +10-15% strength vs cast
- **Lower density:** Reduces expensive elements (Re, W, Ta)
- **Quick tests:** Use `--iterations 1` (~30-60s)
