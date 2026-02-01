import requests
import sys
import os

# Configuration
MARKETPLACE_URL = "http://127.0.0.1:5000"  # Change this to your deployed URL

def pull_agent(agent_name, version=None):
    """
    1. Asks Marketplace for the download URL of the agent.
    2. Downloads the zip file.
    """
    print(f"🔍 Searching for '{agent_name}' on marketplace...")
    
    # Step 1: Get Metadata
    try:
        url = f"{MARKETPLACE_URL}/api/pull/{agent_name}"
        if version:
            url += f"?version={version}"
        response = requests.get(url)
        if response.status_code == 404:
            print(f"❌ Error: Agent '{agent_name}' not found.")
            return
        
        data = response.json()
        download_url = data['download_url']
        version = data['version']
        print(f"⬇️  Found v{version}. Downloading...")

        # Step 2: Download File
        file_resp = requests.get(download_url)
        filename = f"{agent_name}_v{version}.zip"
        
        with open(filename, 'wb') as f:
            f.write(file_resp.content)
            
        print(f"✅ Successfully downloaded: {filename}")
        print(f"   Run 'unzip {filename}' to install.")
        
    except Exception as e:
        print(f"❌ Connection Error: {e}")

def push_agent(file_path):
    """
    Uploads a zip file to the marketplace via API.
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File '{file_path}' does not exist.")
        return

    print(f"⬆️  Uploading '{file_path}' to marketplace...")
    
    try:
        files = {'file': open(file_path, 'rb')}
        response = requests.post(f"{MARKETPLACE_URL}/api/push", files=files)
        
        if response.status_code == 201:
            print("✅ Upload Success!")
            print(response.json())
        else:
            print(f"❌ Upload Failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python agentica_client.py [push|pull] [filename|agent_name] [--version X]")
        sys.exit(1)

    command = sys.argv[1]
    target = sys.argv[2]
    version = None
    if "--version" in sys.argv:
        idx = sys.argv.index("--version")
        if idx + 1 < len(sys.argv):
            version = sys.argv[idx + 1]

    if command == "pull":
        pull_agent(target, version)
    elif command == "push":
        push_agent(target)
    else:
        print("Unknown command. Use 'push' or 'pull'.")
