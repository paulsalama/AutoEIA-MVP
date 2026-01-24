#!/bin/bash
# AutoEIA Development Environment Startup Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting AutoEIA Development Environment${NC}\n"

# Check if running from project root
if [ ! -d "platform/frontend" ] || [ ! -d "platform/backend" ]; then
    echo -e "${RED}Error: Must be run from project root directory${NC}"
    exit 1
fi

# Function to cleanup background processes on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    jobs -p | xargs -r kill 2>/dev/null
    wait
    echo -e "${GREEN}✓ Services stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start Backend
echo -e "${YELLOW}Starting Backend (Flask)...${NC}"
cd platform/backend
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    uv venv
fi

echo -e "${YELLOW}Installing/syncing dependencies...${NC}"
uv sync

echo -e "${GREEN}✓ Backend starting on http://localhost:8000${NC}"
uv run python app.py &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 2

# Start Frontend
echo -e "${YELLOW}Starting Frontend (Vite)...${NC}"
cd ../frontend

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing npm dependencies...${NC}"
    npm install
fi

echo -e "${GREEN}✓ Frontend starting on http://localhost:5173${NC}"
npm run dev &
FRONTEND_PID=$!

# Return to project root
cd ../..

echo -e "\n${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✨ AutoEIA Development Environment Running ✨${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "Frontend: ${GREEN}http://localhost:5173${NC}"
echo -e "Backend:  ${GREEN}http://localhost:8000${NC}"
echo -e "Health:   ${GREEN}http://localhost:8000/api/health${NC}"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}\n"

# Wait for background processes
wait
