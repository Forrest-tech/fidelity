"""One model call with the provider settings the owner entered (Settings → AI). Keys never leave app.ai."""
from __future__ import annotations

import json
import re
import time

from ..ai import config as CF
from ..ai import providers as P


class Model:
    def __init__(self, spec: str):
        """`spec` = "<provider id or kind>:<model>", e.g. "deepseek:deepseek-chat"."""
        who, _, self.model = spec.partition(":")
        s = CF.load()
        prov = CF.provider(s, who) or next((p for p in s.get("providers", []) if p["kind"] == who), None)
        if not prov:
            raise SystemExit(f"no AI provider '{who}' in Settings → AI")
        self.p, self.key = prov, CF.key_for(prov["id"])
        if not self.key:
            raise SystemExit(f"provider '{who}' has no key")
        self.name = f"{prov['kind']}:{self.model}"
        self.tokens_in = self.tokens_out = 0

    def json(self, system: str, user: str, schema: dict, timeout: float = 180.0, tries: int = 4) -> dict:
        err = None
        for n in range(tries):
            try:
                out = P.call(self.p, self.key, self.model, system, user, schema, timeout=timeout)
                self.tokens_in += out["tokens_in"]
                self.tokens_out += out["tokens_out"]
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", out["text"].strip())
                return json.loads(text)
            except P.ProviderError as e:
                err = e.message
                if not e.retry:
                    break
            except ValueError:
                err = "the model did not answer with JSON"
            time.sleep(2 * (n + 1))
        raise RuntimeError(err or "no answer")
