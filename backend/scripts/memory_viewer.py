"""Streamlit UI for viewing Mem0 memories from Moondream captions."""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from dotenv import load_dotenv
from mem0 import MemoryClient

# Load environment variables
load_dotenv()

# Page config
st.set_page_config(
    page_title="JARVIS Memory Viewer",
    page_icon="🧠",
    layout="wide",
)

# Initialize Mem0 client
@st.cache_resource
def get_mem0_client():
    """Get cached Mem0 client."""
    api_key = os.environ.get("MEM0_API_KEY")
    if not api_key:
        return None
    return MemoryClient(api_key=api_key)


def main():
    """Main Streamlit app."""
    st.title("🧠 JARVIS Memory Viewer")
    st.markdown("View and search Moondream video captions stored in Mem0")

    client = get_mem0_client()

    if not client:
        st.error("MEM0_API_KEY not found in environment variables")
        st.code("export MEM0_API_KEY=your_api_key_here")
        return

    # Sidebar
    with st.sidebar:
        st.header("Options")
        view_mode = st.radio("View Mode", ["Browse All", "Search", "Get All (Filters)"])
        limit = st.slider("Max Results", 10, 100, 50)

        st.markdown("---")
        st.caption("ℹ️ 'Browse All' uses get_all(user_id=)")
        st.caption("ℹ️ 'Search' uses search(query, user_id=)")
        st.caption("ℹ️ 'Get All (Filters)' uses get_all(filters=)")

    def display_memories(memories, title="Results"):
        """Helper to display memory list."""
        if not memories:
            st.info("No memories found. Start streaming video to create memories!")
            return

        # Handle different response formats
        if isinstance(memories, dict):
            memory_list = memories.get("memories", memories.get("results", []))
        else:
            memory_list = memories

        st.success(f"Found {len(memory_list)} {title.lower()}")

        for i, memory in enumerate(memory_list):
            with st.expander(f"{title} {i + 1}", expanded=(i < 3)):
                if isinstance(memory, dict):
                    content = memory.get("memory", memory.get("content", str(memory)))
                    metadata = memory.get("metadata", {})
                    memory_id = memory.get("id", "N/A")
                    score = memory.get("score", None)

                    st.markdown(f"**ID:** `{memory_id}`")
                    st.markdown(f"**Content:** {content}")
                    if score is not None:
                        st.markdown(f"**Relevance:** {score:.3f}")

                    if metadata:
                        cols = st.columns(3)
                        if "timestamp" in metadata:
                            cols[0].metric("Timestamp", str(metadata["timestamp"])[:19])
                        if "frame_number" in metadata:
                            cols[1].metric("Frame #", metadata["frame_number"])
                        if "type" in metadata:
                            cols[2].metric("Type", metadata["type"])
                else:
                    st.write(memory)

    if view_mode == "Browse All":
        st.header("📜 Browse All Memories")

        if st.button("🔄 Refresh"):
            st.cache_data.clear()

        with st.spinner("Loading memories..."):
            try:
                # get_all requires AND filter format
                filters = {"AND": [{"user_id": "jarvis"}]}
                st.caption(f"🔍 Getting all memories (filters={filters}, limit={limit})")

                results = client.get_all(filters=filters, limit=limit)

                # Debug: show raw response
                with st.expander("🔧 Debug: Raw API Response", expanded=False):
                    st.json(results if results else {"status": "empty response"})

                display_memories(results, "Memory")

            except Exception as e:
                st.error(f"Error: {e}")
                with st.expander("🔧 Debug: Error Details"):
                    st.code(str(e))

    elif view_mode == "Search":
        st.header("🔍 Search Memories")

        query = st.text_input("Search query", placeholder="What are you looking for?")

        if query:
            with st.spinner("Searching..."):
                try:
                    st.caption(f"🔍 Searching for: '{query}' (user_id='jarvis')")

                    # Search requires filters parameter per Mem0 API
                    filters = {"AND": [{"user_id": "jarvis"}]}
                    results = client.search(query, filters=filters, limit=limit)

                    # Debug
                    with st.expander("🔧 Debug: Raw API Response", expanded=False):
                        st.json(results if results else {"status": "empty response"})

                    display_memories(results, "Result")

                except Exception as e:
                    st.error(f"Search error: {e}")
                    with st.expander("🔧 Debug: Error Details"):
                        st.code(str(e))

    else:  # Get All (Filters)
        st.header("📜 Get All with OR Filter")
        st.info("Using OR filter format")

        if st.button("🔄 Refresh"):
            st.cache_data.clear()

        with st.spinner("Loading memories..."):
            try:
                # Try with OR filter format
                filters = {"OR": [{"user_id": "jarvis"}]}
                st.caption(f"🔍 Fetching memories (filters={filters}, limit={limit})")

                memories = client.get_all(filters=filters, limit=limit)

                # Debug
                with st.expander("🔧 Debug: Raw API Response", expanded=False):
                    st.json(memories if memories else {"status": "empty response"})

                display_memories(memories, "Memory")

            except Exception as e:
                st.error(f"Error: {e}")
                with st.expander("🔧 Debug: Error Details", expanded=True):
                    st.code(str(e))
                    st.markdown("**Troubleshooting:**")
                    st.markdown("- Check if MEM0_API_KEY is valid")
                    st.markdown("- Verify memories exist for user_id='jarvis'")

    # Footer
    st.markdown("---")
    st.markdown("*Powered by Moondream + Mem0*")


if __name__ == "__main__":
    main()
