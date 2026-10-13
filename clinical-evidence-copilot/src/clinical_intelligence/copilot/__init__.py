"""Clinical Evidence Copilot: an isolated application over the existing Engine."""
from .service import build_packet
from .views import render_markdown

__all__ = ['build_packet', 'render_markdown']
