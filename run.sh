#!/bin/bash
set -e

echo "🛡️ Starting AgentPay-Guard Security Gateway System..."

# 1. Setup Backend
echo "📦 Setting up Python Backend..."
cd backend
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

# Run backend in background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# 2. Setup Frontend
echo "💻 Setting up React Frontend Dashboard..."
cd frontend
npm install --silent
npm run dev -- --host &
FRONTEND_PID=$!
cd ..

echo "✅ System Online!"
echo "📡 Backend API: http://localhost:8000"
echo "🖥️  Frontend UI:  http://localhost:5173"

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait