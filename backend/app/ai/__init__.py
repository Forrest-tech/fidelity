# -*- coding: utf-8 -*-
"""AI suggestions. AI only ever suggests: a person (or an exact correction rule) decides what goes into a result.

    config.py      settings, encrypted provider keys, send scope, per-skill level and budget
    providers.py   one call to a provider (Anthropic through its SDK; others through their HTTP APIs)
    skills/        what the AI is asked to do, each with a version, a prompt, an output format and code checks
    gate.py        everything around a call: the iron rules, cache, examples, budget, breaker, the log
"""
