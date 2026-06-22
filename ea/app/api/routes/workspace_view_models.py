try:
    from app.services.office_surface_service import build_workspace_section_payload as workspace_section_payload
except Exception:  # pragma: no cover - compat path when office surface extras are unavailable
    def workspace_section_payload(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

__all__ = ["workspace_section_payload"]
