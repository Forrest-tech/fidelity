# -*- coding: utf-8 -*-
"""Skills: the few specific things the AI is asked to do. Each has a VERSION (part of the cache key, so a new
prompt asks again), a SYSTEM prompt, an output SCHEMA, build() for the request and check() that enforces in code
what the prompt asks for."""
from . import arbitrate, explain, suggest, transcribe

SKILLS = {"arbitrate": arbitrate, "explain": explain, "transcribe": transcribe, "suggest": suggest}
