import os
import time
import requests
from fpdf import FPDF
from dotenv import load_dotenv
from llm_brain import SecurityLLM  # Ensure llm_brain.py is in the same folder

load_dotenv()

# --- 1. The VirusTotal Tool ---
class VirusTotalAgent:
    def __init__(self):
        self.api_key = os.getenv("VT_API_KEY")
        self.base_url = "https://www.virustotal.com/api/v3"
        self.headers = {"x-apikey": self.api_key}

    def scan_url(self, target_url):
        """Submits a URL for scanning and returns the analysis result."""
        endpoint = f"{self.base_url}/urls"
        data = {"url": target_url}
        
        # Submit URL
        try:
            response = requests.post(endpoint, headers=self.headers, data=data)
            if response.status_code != 200:
                return {"error": f"VT Error {response.status_code}: {response.text}"}
            
            analysis_id = response.json()["data"]["id"]
            return self._poll_analysis(analysis_id)
        except Exception as e:
            return {"error": str(e)}

    def scan_file(self, file_name, file_bytes):
        """Uploads a file for scanning and returns the analysis result."""
        endpoint = f"{self.base_url}/files"
        files = {"file": (file_name, file_bytes)}
        
        # Upload File
        try:
            response = requests.post(endpoint, headers=self.headers, files=files)
            if response.status_code != 200:
                return {"error": f"VT Error {response.status_code}: {response.text}"}
            
            analysis_id = response.json()["data"]["id"]
            return self._poll_analysis(analysis_id)
        except Exception as e:
            return {"error": str(e)}

    def _poll_analysis(self, analysis_id):
        """Internal helper: Polls the analysis endpoint until status is completed."""
        endpoint = f"{self.base_url}/analyses/{analysis_id}"
        
        # Poll up to 10 times (20 seconds max)
        for _ in range(10):
            response = requests.get(endpoint, headers=self.headers)
            if response.status_code == 200:
                result = response.json()
                status = result["data"]["attributes"]["status"]
                
                if status == "completed":
                    return self._format_result(result)
            
            time.sleep(2) 
            
        return {"error": "Analysis timed out. Try checking VirusTotal later manually."}

    def _format_result(self, raw_json):
        """Extracts key data for clean presentation."""
        attrs = raw_json["data"]["attributes"]
        stats = attrs["stats"]
        
        return {
            "status": "completed",
            "malicious": stats["malicious"],
            "suspicious": stats["suspicious"],
            "harmless": stats["harmless"],
            "score": f"{stats['malicious']}/{stats['malicious'] + stats['harmless']}",
            "scan_date": attrs.get("date", "N/A"),
            "details": raw_json 
        }

# --- 2. The PDF Reporter ---
class PDFReporter:
    def generate(self, target, data, llm_summary=""):
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, txt="AI Security Analysis Report", ln=True, align='C')
        pdf.ln(10)
        
        # Target Info
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"Target: {target}", ln=True, align='L')
        pdf.ln(5)
        
        # LLM Summary Section
        if llm_summary:
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(0, 10, txt="AI Assessment:", ln=True)
            pdf.set_font("Arial", '', 11)
            # multi_cell handles line breaks for long text
            pdf.multi_cell(0, 10, txt=llm_summary)
            pdf.ln(10)

        # Technical Results
        if "error" in data:
            pdf.set_text_color(255, 0, 0)
            pdf.cell(0, 10, txt=f"Error: {data['error']}", ln=True)
        else:
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 10, txt="Technical Statistics:", ln=True)
            
            pdf.set_font("Arial", '', 12)
            pdf.set_text_color(255, 0, 0) if data['malicious'] > 0 else pdf.set_text_color(0, 128, 0)
            pdf.cell(0, 10, txt=f"Malicious Engines: {data['malicious']}", ln=True)
            
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 10, txt=f"Suspicious Engines: {data['suspicious']}", ln=True)
            pdf.cell(0, 10, txt=f"Harmless Engines: {data['harmless']}", ln=True)
            
        filename = f"report_{int(time.time())}.pdf"
        pdf.output(filename)
        return filename

# --- 3. The Orchestrator (The "Brain" Wrapper) ---
class AgentOrchestrator:
    def __init__(self):
        # We instantiate the tools here. 
        # This requires VirusTotalAgent and PDFReporter to be defined ABOVE this class.
        self.vt_tool = VirusTotalAgent() 
        self.llm = SecurityLLM()
        self.reporter = PDFReporter()

    def handle_text_input(self, user_text):
        """Main entry point for Chat/URL flows."""
        decision = self.llm.decide_action(user_text)
        
        if decision['action'] == 'chat':
            return {
                "type": "chat", 
                "message": decision['response']
            }
            
        elif decision['action'] == 'scan_url':
            url = decision['target']
            scan_data = self.vt_tool.scan_url(url)
            analysis = self.llm.generate_security_report(url, scan_data)
            pdf_path = self.reporter.generate(url, scan_data, llm_summary=analysis)
            
            return {
                "type": "report",
                "target": url,
                "data": scan_data,
                "summary": analysis,
                "pdf": pdf_path
            }

    def handle_file_upload(self, filename, file_bytes):
        """Main entry point for File flows."""
        scan_data = self.vt_tool.scan_file(filename, file_bytes)
        analysis = self.llm.generate_security_report(filename, scan_data)
        pdf_path = self.reporter.generate(filename, scan_data, llm_summary=analysis)
        
        return {
            "type": "report",
            "target": filename,
            "data": scan_data,
            "summary": analysis,
            "pdf": pdf_path
        }
