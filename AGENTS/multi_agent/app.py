import streamlit as st
import asyncio
import os
import sys
from dotenv import load_dotenv

# Load Env
load_dotenv()

# Import your workflow components
import anthropic
from mcp_manager import MCPManager
from state import WorkflowState
from agents import ResearchAgent, PlannerAgent, DeveloperAgent
from publisher import PublisherAgent

# --- UI CONFIGURATION ---
st.set_page_config(page_title="Agentic Workflow Orchestrator", page_icon="🤖", layout="wide")

st.title("🤖 Agentic AI Orchestrator")
st.markdown("### Research → Plan → Implement → Publish")

# Sidebar for Config
with st.sidebar:
    st.header("Configuration")
    api_key = st.text_input("Anthropic API Key", value=os.environ.get("ANTHROPIC_API_KEY", ""), type="password")
    gh_token = st.text_input("GitHub Token", value=os.environ.get("GITHUB_TOKEN", ""), type="password")
    
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key
    if gh_token:
        os.environ["GITHUB_TOKEN"] = gh_token

    st.info("Ensure your `.env` file is loaded or enter keys above.")

# Main Input
user_request = st.text_area("What would you like to build?", height=100, placeholder="e.g., Create a Python script that analyzes stock prices using yfinance...")

# Container for Real-time Logs
log_container = st.empty()

def streamlit_logger(message):
    """Custom logger that appends messages to the Streamlit UI"""
    # We use session state to keep track of logs across re-renders
    if "logs" not in st.session_state:
        st.session_state.logs = []
    
    st.session_state.logs.append(message)
    
    # Render logs
    with log_container.container():
        for log in st.session_state.logs:
            st.markdown(log)

async def run_workflow(request):
    # Clear previous logs
    st.session_state.logs = []
    streamlit_logger("🚀 **[Orchestrator]** Initializing Workflow...")
    
    mcp = MCPManager()
    client = anthropic.AsyncAnthropic()
    
    try:
        await mcp.connect_servers()
        state = WorkflowState(original_request=request)
        
        # 1. Research
        researcher = ResearchAgent(client, mcp, log_callback=streamlit_logger)
        state = await researcher.execute(state)
        
        # 2. Plan
        planner = PlannerAgent(client, mcp, log_callback=streamlit_logger)
        state = await planner.execute(state)
        
        # 3. Implement
        developer = DeveloperAgent(client, mcp, log_callback=streamlit_logger)
        state = await developer.execute(state)
        
        # 4. Publish
        if state.validation_status.passed:
            publisher = PublisherAgent(client, mcp, log_callback=streamlit_logger)
            state = await publisher.execute(state)
            
            # Show Final Code in UI
            st.subheader("🎉 Generated Code")
            st.code(state.code_artifacts.get('main.py', '# No code generated'), language='python')
        else:
            streamlit_logger("⚠️ Validation failed.")
            
    except Exception as e:
        streamlit_logger(f"❌ **Error:** {str(e)}")
    finally:
        await mcp.cleanup()

# Trigger Button
if st.button("🚀 Launch Workflow", type="primary"):
    if not user_request:
        st.warning("Please enter a task first.")
    else:
        with st.spinner("Agents are working..."):
            # Run Async Loop
            asyncio.run(run_workflow(user_request))
