"""Streamlit Frontend for Cognitive Book OS."""

import streamlit as st
import requests
import json
from pathlib import Path

st.set_page_config(
    page_title="Cognitive Book OS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = "http://localhost:8001"

# --- Sidebar ---
st.sidebar.title("🧠 Cognitive Book OS")
st.sidebar.markdown("---")

# Data Loading
@st.cache_data(ttl=5)
def get_brains():
    try:
        response = requests.get(f"{API_URL}/brains")
        if response.status_code == 200:
            return response.json()
    except:
        return []
    return []

brains = get_brains()
brain_names = [b["name"] for b in brains]
if brain_names:
    selected_brain_name = st.sidebar.selectbox("Select Brain", brain_names)
else:
    selected_brain_name = None
    st.sidebar.info("No brains yet. Use 'Ingest New Brain' to create your first one.")

# Find selected brain object
selected_brain = next((b for b in brains if b["name"] == selected_brain_name), None)

if selected_brain:
    st.sidebar.caption(selected_brain["objective"][:100] + "...")
    st.sidebar.metric("Files", selected_brain["file_count"])

st.sidebar.markdown("---")
mode = st.sidebar.radio("Mode", ["Chat", "Knowledge Explorer", "Graph Visualizer", "Ingest New Brain"])

st.sidebar.markdown("---")
if st.sidebar.button("Refresh Brains"):
    st.cache_data.clear()
    st.rerun()

# --- Main Content ---

# Special case for Ingest Mode - doesn't require a selected brain
if mode == "Ingest New Brain":
    st.header("Ingest New Document")
    st.info("Upload a PDF to create a new Cognitive Brain.")
    
    with st.form("ingest_form"):
        uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
        
        c1, c2 = st.columns(2)
        with c1:
            new_brain_name = st.text_input("Brain Name", placeholder="steve_jobs_bio")
        with c2:
            strategy = st.selectbox("Strategy", ["standard", "triage"])
            
        objective = st.text_area("Objective", placeholder="What do you want to learn from this document?", height=100)
        
        submitted = st.form_submit_button("Start Ingestion")
        
        if submitted:
            if not uploaded_file:
                st.error("Please upload a file.")
            elif not new_brain_name:
                st.error("Please enter a brain name.")
            elif strategy == "triage" and not objective:
                st.error("Strategy 'triage' requires an objective.")
            else:
                # Default objective for standard if empty
                final_objective = objective
                if not final_objective and strategy == "standard":
                    final_objective = "General Comprehensive Knowledge Extraction (Capture all significant structure, facts, and themes)"
                
                with st.spinner("Uploading and starting ingestion..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                        data = {
                            "brain_name": new_brain_name,
                            "objective": final_objective,
                            "strategy": strategy
                        }
                        
                        response = requests.post(f"{API_URL}/ingest", files=files, data=data)
                        
                        if response.status_code == 200:
                            res_json = response.json()
                            st.success(f"Success! {res_json['message']}")
                            st.info(f"Job ID: {res_json['job_id']}")
                            st.warning("Ingestion runs in the background. Check 'Refresh Brains' in a few minutes.")
                        else:
                            st.error(f"Error: {response.text}")
                            
                    except Exception as e:
                        st.error(f"Failed to connect to backend: {e}")
    st.stop()


if not selected_brain:
    st.info("Please select a brain from the sidebar (or ensure backend is running).")
    st.code(f"uv run python -m src.cognitive_book_os.server", language="bash")
    st.stop()

if mode == "Chat":
    st.header(f"Chat with {selected_brain_name}")
    
    with st.sidebar:
        st.markdown("### Chat Settings")
        st.checkbox("Enable Active Learning (Auto-Enrich)", key="auto_enrich", help="If checked, the system will automatically scan skipped chapters if it doesn't know the answer.")
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Brain-specific history key
    history_key = f"msg_{selected_brain_name}"
    if history_key not in st.session_state:
        st.session_state[history_key] = []
        
    # Display chat messages from history on app rerun
    for message in st.session_state[history_key]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "sources" in message:
                with st.expander("Sources"):
                    for s in message["sources"]:
                        st.markdown(f"- {s}")

    # Accept user input
    if prompt := st.chat_input(f"Ask {selected_brain_name}..."):
        # Add user message to chat history
        st.session_state[history_key].append({"role": "user", "content": prompt})
        
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(prompt)
            
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("Thinking...")
            
            try:
                # Get Auto-Enrich setting (could be in sidebar, but let's put it here or default True)
                # Ideally, we add a checkbox near the chat input or in sidebar settings
                # For now, let's hardcode True or make it a sidebar option in "Chat Mode" section
                
                response = requests.post(
                    f"{API_URL}/brains/{selected_brain_name}/query",
                    json={
                        "question": prompt, 
                        "provider": "minimax",
                        "auto_enrich": True if st.session_state.get("auto_enrich", False) else False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    answer = result["answer"]
                    sources = result["sources"]
                    
                    message_placeholder.markdown(answer)
                    if sources:
                        with st.expander("Sources"):
                            for s in sources:
                                st.markdown(f"- {s}")
                                
                    st.session_state[history_key].append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources
                    })
                else:
                    message_placeholder.error(f"Error: {response.status_code} - {response.text}")
                    
            except Exception as e:
                message_placeholder.error(f"Failed to connect to backend: {e}")

elif mode == "Knowledge Explorer":
    st.header(f"Exploring {selected_brain_name}")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Structure")
        try:
            struct_res = requests.get(f"{API_URL}/brains/{selected_brain_name}/structure")
            if struct_res.status_code == 200:
                structure = struct_res.json()["structure"]
                st.code(structure, language=None)
            
            # File picker (simple list for now)
            # Fetch generic file list or just hardcode common dirs?
            # Creating a text input for path is easier for V1
            file_path = st.text_input("Enter file path to view/edit", placeholder="characters/alice.md")
            load_btn = st.button("Load File")
        except Exception as e:
            st.error(str(e))
            
    with col2:
        st.subheader("Content")
        if 'editor_content' not in st.session_state:
            st.session_state.editor_content = ""
            
        if load_btn and file_path:
            try:
                res = requests.get(f"{API_URL}/brains/{selected_brain_name}/files/{file_path}")
                if res.status_code == 200:
                    st.session_state.editor_content = res.json()["content"]
                    st.session_state.current_file = file_path
                else:
                    st.error("File not found")
            except Exception as e:
                st.error(str(e))
                
        # Simple Text Area for editing
        if st.session_state.editor_content or True:
             new_content = st.text_area("Editor", value=st.session_state.editor_content, height=600)
             
             if st.button("Save Changes (Notes Only)"):
                 if "current_file" in st.session_state and st.session_state.current_file.startswith("notes/"):
                     try:
                         requests.post(
                             f"{API_URL}/brains/{selected_brain_name}/notes",
                             json={"path": st.session_state.current_file, "content": new_content}
                         )
                         st.success("Saved!")
                     except Exception as e:
                         st.error(str(e))
                 else:
                     st.warning("You can only edit files in the 'notes/' directory via GUI.")

elif mode == "Graph Visualizer":
    st.header(f"Knowledge Graph: {selected_brain_name}")
    
    if st.button("Regenerate Graph"):
        with st.spinner("Generating graph..."):
            # Call CLI viz command via subprocess? Or API
            # Ideally API. For now, we can use the existing `viz.py` logic if exposed.
            # But the server has a placeholder.
            pass
            
    st.info("Interactive Graph Visualization is coming soon via iframe embedding!")
    # To implement: use streamlit.components.v1.html(open("graph.html").read())
