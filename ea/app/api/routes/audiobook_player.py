from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.services.audiobook_epub_pipeline import resolve_player_scoped_audiobook_file


router = APIRouter(tags=["audiobook-player"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="player_audiobook_not_found")


@router.get("/internal/audiobooks/player/{token}")
def player_scoped_audiobook(token: str, download: bool = False):
    try:
        target_path, metadata = resolve_player_scoped_audiobook_file(token)
    except Exception as exc:
        raise _not_found() from exc

    relative_url = f"/internal/audiobooks/player/{token}"
    if download:
        response = FileResponse(
            target_path,
            media_type=str(metadata.get("content_type") or "audio/mp4").strip() or "audio/mp4",
            filename=str(metadata.get("filename") or target_path.name).strip() or target_path.name,
        )
        response.headers["cache-control"] = "no-store"
        return response

    payload = {
        **metadata,
        "download_url": f"{relative_url}?download=1",
        "vendor_token_exposed": False,
        "raw_library_path_exposed": False,
    }
    return JSONResponse(payload, headers={"cache-control": "no-store"})
