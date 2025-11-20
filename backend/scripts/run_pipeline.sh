#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Configuration
DATA_FILE="scrape/Data_Grok/data_clean_deduplicated_20251120.jsonl"
WEAVIATE_COMPOSE="docker/docker-compose-weaviate.yml"
WEAVIATE_DATA_DIR="docker/weaviate_data"

echo "==========================================="
echo "   Starting AlloyMind Data Pipeline"
echo "==========================================="

# 1. Reset Weaviate
echo "[1/5] Resetting Weaviate Environment..."
docker compose -f $WEAVIATE_COMPOSE down
if [ -d "$WEAVIATE_DATA_DIR" ]; then
    echo "      Removing old data volume..."
    rm -rf $WEAVIATE_DATA_DIR
fi
docker compose -f $WEAVIATE_COMPOSE up -d
echo "      Waiting 10s for Weaviate to initialize..."
sleep 10

# 2. Setup Environment
echo "[2/5] Setting up Virtual Environment..."
if [ ! -d ".venv" ]; then
    echo "      Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "      Installing dependencies..."
pip install -r ../requirements.txt > /dev/null 2>&1

# 3. Generate Ontology
echo "[3/5] Generating Ontology Schema..."
python pipeline/build_ontology.py

# 4. Populate GraphDB
echo "[4/5] Populating GraphDB from $DATA_FILE..."
export ALLOY_JSON=$DATA_FILE
python pipeline/enrich_graphdb.py

# 5. Weaviate Ingestion
echo "[5/5] Setting up Weaviate..."
echo "      Creating Schema..."
python pipeline/weaviate_schema.py
echo "      Ingesting Data..."
python pipeline/weaviate_ingest.py

echo "==========================================="
echo "   Pipeline Completed Successfully! 🚀"
echo "==========================================="
