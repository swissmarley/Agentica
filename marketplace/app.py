import os
import json
import zipfile
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super_secret_agentica_key'

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'zip'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Database ---
agents_db = [
    {
        "id": "hr-agent-v1",
        "name": "hr_agent",
        "version": "0.1.0",
        "description": "Automates CV screening using Gemini.",
        "tags": ["release", "hr", "automation"],
        "author": "System",
        "filename": "hr_agent_v0.1.0.agentica.zip"
    }
]


def _parse_version(version: str):
    parts = []
    for item in version.split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _group_agents(agents):
    grouped = {}
    for agent in agents:
        name = agent.get("name", "")
        if not name:
            continue
        grouped.setdefault(name, []).append(agent)
    result = []
    for name, items in grouped.items():
        items_sorted = sorted(items, key=lambda a: _parse_version(a.get("version", "0")), reverse=True)
        latest = items_sorted[0]
        result.append(
            {
                "name": name,
                "latest": latest,
                "versions": items_sorted,
            }
        )
    result.sort(key=lambda entry: entry["name"].lower())
    return result

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_manifest(zip_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            manifest_file = next((f for f in z.namelist() if f.endswith('agentica_manifest.json')), None)
            if manifest_file:
                with z.open(manifest_file) as f:
                    return json.load(f)
    except Exception as e:
        print(f"Error reading zip: {e}")
    return None

# --- WEB ROUTES (Browser) ---

@app.route('/')
def index():
    return render_template('index.html', agents=_group_agents(agents_db))

@app.route('/upload', methods=['POST'])
def upload_agent():
    # ... (Keep existing browser upload logic or refactor to use api_push) ...
    # For brevity, reusing the logic here is fine, but let's keep it separate for clarity.
    if 'agent_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('index'))
    file = request.files['agent_file']
    if file and allowed_file(file.filename):
        process_upload(file) # Refactored helper below
        flash('Agent uploaded successfully!', 'success')
        return redirect(url_for('index'))
    flash('Invalid file.', 'error')
    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_agent(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

# --- API ROUTES (Agentica CLI/App Integration) ---

@app.route('/api/push', methods=['POST'])
def api_push():
    """Endpoint for Agentica App to push agents directly."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file and allowed_file(file.filename):
        agent_data = process_upload(file)
        if agent_data:
            return jsonify({"status": "success", "agent": agent_data}), 201
        else:
            return jsonify({"error": "Invalid manifest"}), 400
    return jsonify({"error": "Invalid file type"}), 400

@app.route('/api/pull/<agent_name>', methods=['GET'])
def api_pull(agent_name):
    """Endpoint for Agentica App to find and download an agent."""
    # Find agent by name (getting the latest version typically)
    requested_version = request.args.get("version")
    matching = [a for a in agents_db if a.get("name") == agent_name]
    if requested_version:
        agent = next((a for a in matching if a.get("version") == requested_version), None)
    else:
        agent = None
        if matching:
            agent = sorted(matching, key=lambda a: _parse_version(a.get("version", "0")), reverse=True)[0]
    
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
        
    # Return download URL and metadata
    return jsonify({
        "name": agent['name'],
        "version": agent['version'],
        "download_url": url_for('download_agent', filename=agent['filename'], _external=True)
    })

# --- HELPER ---
def process_upload(file):
    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    
    manifest = extract_manifest(save_path)
    if manifest:
        new_agent = {
            "id": str(uuid.uuid4()),
            "name": manifest.get('name', 'Unknown'),
            "version": manifest.get('version', '0.0.1'),
            "description": manifest.get('description', ''),
            "tags": manifest.get('tags', []),
            "author": "API Upload",
            "filename": filename
        }
        agents_db.insert(0, new_agent)
        return new_agent
    else:
        os.remove(save_path)
        return None

if __name__ == '__main__':
    app.run(debug=True, port=5000)
