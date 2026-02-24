#!/bin/bash
# Launch Cognitive Book OS - Backend + React Frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "🧠 Starting Cognitive Book OS..."

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start Backend
echo "🔌 Starting Backend on port 8001..."
uv run uvicorn src.cognitive_book_os.server:app --port 8001 --host 0.0.0.0 &
BACKEND_PID=$!
sleep 2

# Start Frontend
echo "🎨 Starting React Frontend on port 5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ Cognitive Book OS is running!"
echo "   Frontend: http://localhost:5173"
echo "   Backend:  http://localhost:8001"
echo ""
echo "Press Ctrl+C to stop all services."

# Wait for either process to exit
wait
