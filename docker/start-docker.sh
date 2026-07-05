#!/bin/bash
set -e

echo "🚀 Auxilium Manus Docker Setup"
echo "=============================="

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
    echo "📝 Creating environment configuration..."
    cp .env.example .env
    echo "✅ Created .env file from template"
    echo "⚠️  Please edit .env with your actual configuration values before continuing"
    echo ""
    read -p "Press Enter after updating .env file, or Ctrl+C to exit..."
fi

echo "🔨 Building Docker images..."
docker compose build

echo "🚀 Starting Auxilium Manus..."
docker compose up -d

echo ""
echo "✅ Auxilium Manus is starting up!"
echo ""
echo "Services will be available at:"
echo "  🌐 Frontend: http://localhost:3000"
echo "  🔧 Backend API: http://localhost:8000"
echo ""
echo "Ensure Hatchet is running:"
echo "  cd docker/hatchet && docker compose up -d"
echo "  📊 Hatchet dashboard: http://localhost:8888"
echo ""
echo "If Hatchet runs in Docker, restart the app stack with the network override:"
echo "  docker compose -f docker-compose.yml -f docker-compose.hatchet-network.yml up -d"
echo ""
echo "📊 Monitor startup: docker compose logs -f"
echo "🛑 Stop services: docker compose down"
echo ""

sleep 5
docker compose ps
