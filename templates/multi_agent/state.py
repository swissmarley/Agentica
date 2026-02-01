from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ValidationResult(BaseModel):
    passed: bool
    errors: List[str] = []

class WorkflowState(BaseModel):
    """The shared context passed between agents (like n8n binary/json data)"""
    original_request: str
    
    # Phase 1: Research
    research_summary: Optional[str] = None
    relevant_docs: List[str] = []
    
    # Phase 2: Plan
    implementation_plan: Optional[List[str]] = None
    approved_plan: bool = False
    
    # Phase 3: Implementation
    code_artifacts: Dict[str, str] = Field(default_factory=dict)
    validation_status: ValidationResult = Field(default_factory=lambda: ValidationResult(passed=False))
