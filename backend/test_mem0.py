"""Quick test script for Mem0 integration."""
import asyncio
from app.core.mem0_client import mem0_manager

async def test_mem0():
    print("Testing Mem0 Integration...\n")

    # Test 1: Store a memory
    print("1. Storing a test memory...")
    success = await mem0_manager.add_memory(
        content="Test Company raised $5M Series A in 2024",
        metadata={"category": "funding", "test": True}
    )
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}\n")

    # Test 2: Store another memory
    print("2. Storing another test memory...")
    success2 = await mem0_manager.add_memory(
        content="Founder showed strong technical background in AI",
        metadata={"category": "green_flag", "test": True}
    )
    print(f"   Result: {'✅ Success' if success2 else '❌ Failed'}\n")

    # Test 3: Search memories
    print("3. Searching for funding-related memories...")
    results = mem0_manager.search_memories("Series A funding", limit=5)
    print(f"   Found {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"   {i}. {result.get('memory', 'N/A')[:100]}...")
    print()

    # Test 4: Get all memories
    print("4. Getting all memories...")
    all_memories = mem0_manager.get_all_memories(limit=10)
    print(f"   Total memories: {len(all_memories)}")
    print()

    print("✅ Mem0 test complete!")

if __name__ == "__main__":
    asyncio.run(test_mem0())
