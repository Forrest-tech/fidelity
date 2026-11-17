"""Run a legacy check-style suite (scripts/*.py with check()/eq() + _RESULTS)
and expose every individual check as its own pytest case, so none is lost."""
import contextlib
import io


def collect(module, fn_names):
    """Run the suite's test functions once; return [(id, ok, detail)]."""
    module._RESULTS.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        for name in fn_names:
            getattr(module, name)()
    out = []
    for i, (name, ok, detail) in enumerate(module._RESULTS):
        out.append(("%03d %s" % (i, name), ok, detail))
    return out
