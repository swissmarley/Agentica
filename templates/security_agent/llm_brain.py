import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class SecurityLLM:
    def __init__(self):
        # Initialize OpenAI client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # System prompt defines the persona
        self.system_prompt = """
        You are 'Sentinel', an elite Cybersecurity AI Agent.
        Your responsibilities:
        1. Analyze user inputs to detect URLs that need scanning.
        2. Summarize complex VirusTotal JSON reports into clear, executive summaries.
        3. Provide safety advice based on scan results.
        
        Tone: Professional, vigilant, and concise.
        """

    def decide_action(self, user_input):
        """
        Orchestrator: Decides if the input requires a tool (Scan) or is just chat.
        Returns JSON: {"action": "scan_url" | "chat", "target": "url_if_found" | null, "response": "chat_response_if_needed"}
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini", # Or your preferred model
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an orchestrator. If the user provides a URL or asks to check a link, return JSON with action='scan_url' and extract the target. If it's general conversation, return action='chat' and a helpful response. Output strictly JSON."},
                {"role": "user", "content": user_input}
            ]
        )
        return json.loads(response.choices[0].message.content)

    def generate_security_report(self, target, scan_data):
        """
        Synthesizer: Converts raw VirusTotal JSON into a readable assessment.
        """
        prompt = f"""
        Analyze this VirusTotal scan result for '{target}':
        {json.dumps(scan_data)}
        
        Write a brief 3-sentence security assessment. 
        - Start with a clear VERDICT (SAFE, SUSPICIOUS, or MALICIOUS).
        - Mention key stats (e.g., 5/90 engines detected it).
        - Give a recommended action for the user.
        """
        
        response = self.client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
