import os
import requests
from agents import BaseAgent
from state import WorkflowState
import config

class PublisherAgent(BaseAgent):
    async def execute(self, state: WorkflowState) -> WorkflowState:
        self.log("\n📦 **[Publisher]** Starting deployment phase...")
        
        # 1. SAVE LOCALLY
        self._save_local_report(state)
        
        # 2. PUSH TO GITHUB
        await self._create_github_issue(state)
        
        return state

    def _save_local_report(self, state: WorkflowState):
        """Saves the full report and code artifacts to a local folder"""
        # Ensure output directory exists
        if not os.path.exists(config.OUTPUT_DIR):
            os.makedirs(config.OUTPUT_DIR)
            
        # 1. Prepare Report Content
        report_content = f"""# Agentic Workflow Report
**Task:** {state.original_request}

## 1. Research Findings
{state.research_summary}

## 2. Implementation Plan
{state.implementation_plan}

## 3. Code Artifacts
"""
        # 2. Save Code Files
        saved_files = []
        for filename, code in state.code_artifacts.items():
            # Append code to the markdown report
            report_content += f"\n### {filename}\n```python\n{code}\n```\n"
            
            # Save individual code file to disk
            file_path = os.path.join(config.OUTPUT_DIR, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            saved_files.append(filename)
                
        # 3. Save the Markdown Report
        report_path = os.path.join(config.OUTPUT_DIR, "final_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
            
        # Get absolute path for clarity in logs
        abs_path = os.path.abspath(config.OUTPUT_DIR)
        self.log(f"✅ **[Publisher]** Saved {len(saved_files)} files to: `{abs_path}`")

    async def _create_github_issue(self, state: WorkflowState):
        self.log(f"   → Creating GitHub Issue in `{config.GITHUB_REPO}`...")
        
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            self.log("⚠️ **[Publisher]** No GITHUB_TOKEN found. Skipping GitHub.")
            return

        url = f"https://api.github.com/repos/{config.GITHUB_REPO}/issues"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        body = f"**Research:**\n{state.research_summary[:500]}...\n\n**Plan:**\n{state.implementation_plan}"
        payload = {
            "title": f"Agent Result: {state.original_request[:50]}",
            "body": body,
            "labels": ["agent-generated"]
        }

        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 201:
                link = resp.json().get('html_url')
                self.log(f"✅ **[Publisher]** GitHub Issue Created: [Link]({link})")
            else:
                self.log(f"❌ **[Publisher]** GitHub Error {resp.status_code}: {resp.text}")
        except Exception as e:
            self.log(f"❌ **[Publisher]** Connection failed: {e}")
