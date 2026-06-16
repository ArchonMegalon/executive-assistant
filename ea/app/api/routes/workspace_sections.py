from __future__ import annotations

from app.product.models import ProductSnapshot
from app.services.office_surface_service import build_workspace_section_payload


def workspace_section_payload(
    section: str,
    snapshot: ProductSnapshot,
    diagnostics: dict[str, object] | None = None,
    outcomes: dict[str, object] | None = None,
    *,
    operator_id: str = "",
    brand_key: str = "",
) -> dict[str, object]:
    return build_workspace_section_payload(
        section,
        snapshot,
        diagnostics,
        outcomes,
        operator_id=operator_id,
        brand_key=brand_key,
    )


__all__ = ["workspace_section_payload"]
