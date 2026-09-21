"""jev-skill-selection: filter which agent skills enter the prompt before the first LLM call.

Unlike skill *suggesters* (pick at most one skill name), this library keep/drops many
skills from a closed catalog to shrink injected context.
"""

from .catalog import Skill, load_catalog
from .models import SelectionOptions, SelectionResult, SkillDecision
from .select import select_skills

__version__ = "0.1.0"
__all__ = [
    "Skill",
    "SkillDecision",
    "SelectionOptions",
    "SelectionResult",
    "load_catalog",
    "select_skills",
    "__version__",
]
