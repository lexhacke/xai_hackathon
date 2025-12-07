# 🧠 Voice-Activated Mem0 Assistant

Talk to your AI and search through your Mem0 memories using voice! This demo combines:
- **Grok Voice API** - Real-time voice conversations
- **Function Calling** - AI triggers memory search automatically
- **Mem0** - Your persistent memory storage

## 🎯 Features

- 🎤 **Voice Search**: "What did I see about cars?"
- 📝 **Recent Memories**: "Show me my last 10 memories"
- 🔍 **Smart Queries**: AI understands natural language
- ⚡ **Real-time**: Instant function calling and results

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd grok-voice-mem0-demo
pip install -r requirements.txt
```

### 2. Configure Environment

The `.env` file is already set up with your keys:
- ✅ XAI_API_KEY
- ✅ MEM0_API_KEY

### 3. Start Backend

```bash
python backend.py
```

Output:
```
🚀 Starting Voice Mem0 Assistant
📡 Server: http://localhost:8000
🎙️  WebSocket: ws://localhost:8000/ws
```

### 4. Open Client

Open `client.html` in your browser (Chrome recommended):
```bash
open client.html
```

Or navigate to: `file:///path/to/grok-voice-mem0-demo/client.html`

### 5. Start Talking!

1. Click **"🎤 Start Talking"**
2. Grant microphone access
3. Ask about your memories!

## 💬 Example Questions

Try saying:
- "What did I see in the video about cars?"
- "Show me my recent memories"
- "Search for memories about people walking"
- "What was that memory about the red building?"
- "Find memories from yesterday"

## 🔧 How It Works

```
1. You speak → "What memories do I have about cars?"
2. AI understands → Calls search_memories("cars")
3. Backend executes → Queries Mem0 API
4. Results returned → AI speaks: "I found 3 memories about cars..."
```

## 📋 Available Functions

### `search_memories(query, limit)`
Search through stored memories by content.

**Example:**
```javascript
{
  "query": "cars",
  "limit": 5
}
```

### `get_recent_memories(limit)`
Get the most recent memories.

**Example:**
```javascript
{
  "limit": 10
}
```

## 🔍 Testing Without Voice

You can test the backend directly:

```bash
# Check health
curl http://localhost:8000/health

# Check available tools
curl http://localhost:8000/
```

## 🧪 Debug Mode

Watch the terminal while talking to see:
- 🔍 Memory searches
- 📞 Function calls
- ✅ Results
- ❌ Errors

## 🎨 Architecture

```
┌─────────────┐   WebSocket   ┌─────────────┐   Function    ┌─────────┐
│   Browser   │ ←───────────→ │   Backend   │ ←───Calling──→ │  Mem0   │
│  (client)   │   Audio+Text  │  (FastAPI)  │   Search       │   API   │
└─────────────┘               └─────────────┘                └─────────┘
                                      ↕
                              WebSocket to Grok
                                  Voice API
```

## 🐛 Troubleshooting

**No audio?**
- Check microphone permissions in browser
- Use Chrome/Edge (best WebRTC support)

**Connection failed?**
- Verify backend is running on port 8000
- Check `.env` file has valid API keys

**No memories found?**
- Make sure you have memories in Mem0 for `user_id="jarvis"`
- Test with your Streamlit UI first

**Function not called?**
- Check backend logs for function execution
- Make sure you phrase questions clearly

## 📦 Files

```
grok-voice-mem0-demo/
├── backend.py       # FastAPI server with function calling
├── client.html      # Web interface for voice
├── .env             # API keys (configured)
├── requirements.txt # Python dependencies
└── README.md        # This file
```

## 🔑 API Keys

Your keys are already configured in `.env`:
- `XAI_API_KEY` - For Grok Voice API
- `MEM0_API_KEY` - For memory storage

## 🎉 Next Steps

1. **Add more functions:**
   - Delete memories
   - Update memories
   - Filter by date/metadata

2. **Enhance UI:**
   - Show function results visually
   - Display memory content
   - Add memory creation

3. **Deploy:**
   - Use ngrok for public access
   - Add authentication
   - Deploy to cloud

## 📚 Resources

- [Grok Voice API Docs](https://x.ai/api)
- [Mem0 Documentation](https://docs.mem0.ai)
- [Function Calling Guide](Grok-Voice-Agent-API-Docs-Final.pdf) (page 9-13)

---

**Built with ❤️ using Grok Voice API + Mem0**
