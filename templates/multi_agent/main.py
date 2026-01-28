import asyncio
import os
import sys

# --- NEW: Load .env file immediately ---
from dotenv import load_dotenv
# This loads variables from .env into os.environ
load_dotenv() 
# ---------------------------------------

import anthropic
import config
from mcp_manager import MCPManager
from state import WorkflowState
from agents import ResearchAgent, PlannerAgent, DeveloperAgent
from publisher import PublisherAgent

async def tech_lead_orchestrator():
    print("🚀 [Orchestrator] Initializing Workflow...")
    
    # Check for keys NOW, after loading .env
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ CRITICAL: ANTHROPIC_API_KEY not found in .env or environment.")
        print("   Please create a .env file with ANTHROPIC_API_KEY=sk-...")
        return

    if not os.environ.get("GITHUB_TOKEN"):
        print("⚠️  WARNING: GITHUB_TOKEN not found. GitHub publishing will be skipped.")

    mcp = MCPManager()
    
    try:
        # Initialize Anthropic Client
        client = anthropic.AsyncAnthropic()
        
        # Connect to tools
        await mcp.connect_servers()
        
        # --- DEFINE REQUEST ---
        # You can change this request or make it an input()
        user_request = input("Describe your project: ")
        print(f"🎯 Target: {user_request}\n")
        
        state = WorkflowState(original_request=user_request)
        
        # --- PHASE 1: RESEARCH ---
        researcher = ResearchAgent(client, mcp)
        state = await researcher.execute(state)
        
        # --- PHASE 2: PLAN ---
        planner = PlannerAgent(client, mcp)
        state = await planner.execute(state)
        
        # --- PHASE 3: IMPLEMENT ---
        developer = DeveloperAgent(client, mcp)
        state = await developer.execute(state)
        
        # --- PHASE 4: PUBLISH (Local + GitHub) ---
        if state.validation_status.passed:
            publisher = PublisherAgent(client, mcp)
            state = await publisher.execute(state)
        else:
            print("⚠️  Validation failed. Skipping publication phase.")

        print("\n--- Workflow Complete ---")
            
    except anthropic.APIError as e:
        print(f"\n❌ Anthropic API Error: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await mcp.cleanup()

if __name__ == "__main__":
    try:
        # Windows/Event Loop Policy fix (optional, good for compatibility)
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        asyncio.run(tech_lead_orchestrator())
    except KeyboardInterrupt:
        print("\n👋 User cancelled execution.")
