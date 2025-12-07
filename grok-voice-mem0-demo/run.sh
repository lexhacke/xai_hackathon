#!/bin/bash

echo "🧠 Voice-Activated Mem0 Assistant"
echo "=================================="
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Start backend
echo ""
echo "🚀 Starting backend server..."
echo "📡 Server: http://localhost:8000"
echo "🎙️  WebSocket: ws://localhost:8000/ws"
echo ""
echo "Next steps:"
echo "1. Open client.html in your browser"
echo "2. Click 'Start Talking'"
echo "3. Ask about your memories!"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python backend.py
