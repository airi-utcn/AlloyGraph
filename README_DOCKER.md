# AlloyMind Docker Setup

## Overview

AlloyMind uses a multi-container Docker architecture with three services:

- **Backend** (Flask + Gunicorn): AI-powered alloy design API
- **Frontend** (Vue.js + Nginx): Web interface for alloy evaluation and design
- **Database** (Weaviate): Vector database for alloy knowledge graph

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Frontend      │────▶│    Backend       │────▶│  Weaviate   │
│  Vue.js/Nginx   │     │  Flask/Gunicorn  │     │  Vector DB  │
│   Port 3000     │     │    Port 5001     │     │  Port 8081  │
└─────────────────┘     └──────────────────┘     └─────────────┘
```

## Deployment Modes

### Local Development
Services run in Docker containers on your machine. Frontend and backend are accessible via `localhost`.

**Configuration:**
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5001`
- Set `VITE_API_BASE_URL=http://localhost:5001` in `frontend/.env.production`

### Production Deployment
Containers run on a server and are accessible via public domain/IP.

**Configuration:**
- Frontend: `http://your-domain:3000`
- Backend: `http://your-domain:5001`
- Set `VITE_API_BASE_URL=http://your-domain:5001` in `frontend/.env.production`

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Groq API key ([obtain here](https://console.groq.com/keys))

### Setup

1. **Configure environment:**
   
   Create a `.env` file in the project root with your API key:
   ```bash
   echo "GROQ_API_KEY=your_groq_api_key_here" > .env
   ```

2. **Configure frontend (optional for local dev):**
   
   Edit `frontend/.env.production` to set the backend URL:
   ```bash
   # For local development:
   VITE_API_BASE_URL=http://localhost:5001
   
   # For production deployment:
   VITE_API_BASE_URL=http://your-domain:5001
   ```

3. **Start Weaviate database:**
   ```bash
   cd backend/docker
   docker compose -f docker-compose-weaviate.yml up -d
   cd ../..
   ```

4. **Build and start AlloyMind:**
   ```bash
   docker compose up -d --build
   ```

5. **Access application:**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:5001

## Production Stack

- **WSGI Server:** Gunicorn (4 workers, 120s timeout)
- **Web Server:** Nginx (gzip, caching, SPA routing)
- **Database:** Weaviate (vector embeddings, GraphQL)

## Key Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Service orchestration |
| `backend/Dockerfile` | Backend container definition |
| `frontend/Dockerfile` | Multi-stage frontend build |
| `frontend/nginx.conf` | SPA routing configuration |
| `frontend/.env.production` | Frontend API URL |
