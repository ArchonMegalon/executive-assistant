from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrainProfile:
    profile: str
    lane: str
    public_model: str
    provider_hint_order: tuple[str, ...]
    default_capability_key: str = ""
    backend_key: str = ""
    health_provider_key: str = ""
    review_required: bool = False
    needs_review: bool = False
    risk_labels: tuple[str, ...] = ()
    merge_policy: str = "auto"


DEFAULT_PUBLIC_MODEL = "ea-coder-best"
FAST_PUBLIC_MODEL = "ea-coder-fast"
GROUNDWORK_PUBLIC_MODEL = "ea-groundwork-gemini"
GROUNDWORK_PUBLIC_MODEL_ALIAS = "ea-groundwork"
REVIEW_LIGHT_PUBLIC_MODEL = "ea-review-light"
MAGICX_PUBLIC_MODEL = "ea-magicx-coder"
ONEMIN_PUBLIC_MODEL = "ea-onemin-coder"
SURVIVAL_PUBLIC_MODEL = "ea-coder-survival"
AUDIT_PUBLIC_MODEL = "ea-audit-jury"
AUDIT_PUBLIC_MODEL_ALIAS = "ea-audit"
GEMINI_VORTEX_PUBLIC_MODEL = "ea-gemini-flash"
REPAIR_GEMINI_PUBLIC_MODEL = "ea-repair-gemini"
HARD_BATCH_PUBLIC_MODEL = "ea-coder-hard-batch"
HARD_RESCUE_PUBLIC_MODEL = "ea-coder-hard-rescue"


BRAIN_PROFILES: tuple[BrainProfile, ...] = (
    BrainProfile(
        profile="core",
        lane="hard",
        public_model="ea-coder-hard",
        provider_hint_order=("onemin", "gemini_vortex", "magixai"),
        default_capability_key="code_generate",
        backend_key="onemin",
        health_provider_key="onemin",
        review_required=True,
        needs_review=True,
        risk_labels=("high_impact", "code_change"),
        merge_policy="require_review",
    ),
    BrainProfile(
        profile="core_batch",
        lane="hard",
        public_model=HARD_BATCH_PUBLIC_MODEL,
        provider_hint_order=("onemin", "gemini_vortex", "magixai"),
        default_capability_key="code_generate",
        backend_key="onemin",
        health_provider_key="onemin",
        review_required=True,
        needs_review=True,
        risk_labels=("high_impact", "code_change", "batch"),
        merge_policy="require_review",
    ),
    BrainProfile(
        profile="core_rescue",
        lane="hard",
        public_model=HARD_RESCUE_PUBLIC_MODEL,
        provider_hint_order=("onemin", "gemini_vortex", "magixai"),
        default_capability_key="code_generate",
        backend_key="onemin",
        health_provider_key="onemin",
        review_required=True,
        needs_review=True,
        risk_labels=("high_impact", "code_change", "batch", "rescue"),
        merge_policy="require_review",
    ),
    BrainProfile(
        profile="easy",
        lane="fast",
        public_model=FAST_PUBLIC_MODEL,
        provider_hint_order=("gemini_vortex", "magixai", "onemin"),
        default_capability_key="code_generate",
        backend_key="gemini_vortex",
        health_provider_key="gemini_vortex",
        risk_labels=("low_impact", "assist"),
        merge_policy="auto",
    ),
    BrainProfile(
        profile="repair",
        lane="repair",
        public_model=FAST_PUBLIC_MODEL,
        provider_hint_order=("gemini_vortex", "magixai", "onemin"),
        default_capability_key="code_generate",
        backend_key="gemini_vortex",
        health_provider_key="gemini_vortex",
        risk_labels=("bounded_patch", "code_change", "follow_up"),
        merge_policy="auto_if_low_risk",
    ),
    BrainProfile(
        profile="groundwork",
        lane="groundwork",
        public_model=GROUNDWORK_PUBLIC_MODEL,
        provider_hint_order=("gemini_vortex",),
        default_capability_key="code_generate",
        backend_key="gemini_vortex",
        health_provider_key="gemini_vortex",
        risk_labels=("non_urgent", "analysis", "design"),
        merge_policy="auto",
    ),
    BrainProfile(
        profile="review_light",
        lane="review",
        public_model=REVIEW_LIGHT_PUBLIC_MODEL,
        provider_hint_order=("onemin", "gemini_vortex", "browseract"),
        default_capability_key="reasoned_patch_review",
        backend_key="onemin",
        health_provider_key="onemin",
        risk_labels=("posthoc", "light_review", "diff_review"),
        merge_policy="auto_if_low_risk",
    ),
    BrainProfile(
        profile="audit",
        lane="audit",
        public_model=AUDIT_PUBLIC_MODEL,
        provider_hint_order=("onemin", "gemini_vortex", "browseract"),
        default_capability_key="reasoned_patch_review",
        backend_key="onemin",
        health_provider_key="onemin",
        review_required=True,
        needs_review=True,
        risk_labels=("publish", "high_risk", "multi_view"),
        merge_policy="require_review",
    ),
    BrainProfile(
        profile="survival",
        lane="survival",
        public_model=SURVIVAL_PUBLIC_MODEL,
        provider_hint_order=("browseract", "gemini_vortex", "onemin"),
        default_capability_key="code_generate",
        backend_key="chatplayground",
        health_provider_key="chatplayground",
        risk_labels=("budget_exhausted", "backup", "slow_path"),
        merge_policy="auto_if_low_risk",
    ),
)


def list_brain_profiles() -> tuple[BrainProfile, ...]:
    return BRAIN_PROFILES


def get_brain_profile(name_or_model: str) -> BrainProfile | None:
    target = str(name_or_model or "").strip()
    for profile in BRAIN_PROFILES:
        if target in {profile.profile, profile.public_model}:
            return profile
    return None
