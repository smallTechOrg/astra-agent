"""Prompt loading, variable validation, and rendering.

Per spec/product/08-prompts.md: resolution order is tenant override then
operator default; `# variables:` header validates at render time; `---`
splits system from user prompt.
"""

from __future__ import annotations

from astra.prompts.resolver import PromptResolver, RenderedPrompt

__all__ = ["PromptResolver", "RenderedPrompt"]
