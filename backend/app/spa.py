from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Serve the built web app; unknown non-API paths get index.html so client-side routes survive a reload."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404 and not path.replace(chr(92), "/").lstrip("/").startswith("api/"):
                return await super().get_response("index.html", scope)
            raise
