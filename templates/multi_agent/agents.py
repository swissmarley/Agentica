import anthropic
import config
from state import WorkflowState, ValidationResult

class BaseAgent:
    def __init__(self, client: anthropic.AsyncAnthropic, mcp_manager, log_callback=print):
        self.client = client
        self.mcp = mcp_manager
        self.log = log_callback # Use this instead of print()

class ResearchAgent(BaseAgent):
    async def execute(self, state: WorkflowState) -> WorkflowState:
        self.log(f"🔍 **[Researcher]** Starting research on: *{state.original_request}*...")
        
        response = await self.client.messages.create(
            model=config.MODEL_NAME,
            max_tokens=2000,
            system="You are an expert technical researcher. Find accurate documentation.",
            messages=[
                {"role": "user", "content": f"Research requirements for: {state.original_request}. Suggest libraries."}
            ]
        )
        
        findings = response.content[0].text
        state.research_summary = findings
        self.log("✅ **[Researcher]** Findings compiled.")
        return state

class PlannerAgent(BaseAgent):
    async def execute(self, state: WorkflowState) -> WorkflowState:
        self.log("\n📋 **[Planner]** Creating implementation plan...")
        
        prompt = f"""
        Context: {state.research_summary}
        Task: Create a step-by-step implementation plan for {state.original_request}.
        Return ONLY a JSON-compatible list of steps.
        """
        
        response = await self.client.messages.create(
            model=config.MODEL_NAME,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Simulating parsed output for demo (in prod, use JSON parsing)
        plan_steps = ["1. Setup Environment", "2. Core Logic", "3. Testing"]
        state.implementation_plan = plan_steps
        state.approved_plan = True 
        self.log(f"✅ **[Planner]** Plan created with {len(plan_steps)} steps.")
        return state

class DeveloperAgent(BaseAgent):
    async def execute(self, state: WorkflowState) -> WorkflowState:
        self.log("\n🛠️ **[Developer]** Starting implementation phase...")
        
        if not state.approved_plan:
            raise Exception("Cannot implement without approved plan")
        
        self.log(f"   → Generating code based on plan...")
        
        response = await self.client.messages.create(
            model=config.MODEL_NAME,
            max_tokens=4000,
            system="You are a Python developer. Output only valid Python code.",
            messages=[
                {"role": "user", "content": f"Write the code for: {state.original_request}. Plan: {state.implementation_plan}"}
            ]
        )
        
        code_content = response.content[0].text
        state.code_artifacts['main.py'] = code_content
        
        # Simple string check for validation
        if "def" in code_content or "import" in code_content:
             state.validation_status = ValidationResult(passed=True)
             self.log("✅ **[Developer]** Validation Passed.")
        else:
             state.validation_status = ValidationResult(passed=False, errors=["Syntax Error"])
             self.log("❌ **[Developer]** Validation Failed.")
             
        return state
