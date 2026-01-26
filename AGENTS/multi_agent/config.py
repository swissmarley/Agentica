# config.py
import os

# Model Configuration
MODEL_NAME = "claude-sonnet-4-5-20250929" 

# Validation
REQUIRED_ENV_VARS = ["ANTHROPIC_API_KEY", "GITHUB_TOKEN"]

# Output Configuration
OUTPUT_DIR = "workflow_outputs"
GITHUB_REPO = "githubuser/githubrepo" # CHANGE THIS or set via env var

MAX_OUTPUT_TOKENS = 8000
