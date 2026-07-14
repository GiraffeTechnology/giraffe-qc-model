"""Provider-neutral classical-CV configuration for authored detection points."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.db.sku_models import QCDetectionPoint
from src.db.studio_models import QCPublishBundle

ALLOWED_ANALYZERS = frozenset({"rhinestone_count", "petal_segmentation", "pistil_localization"})


class InvalidAnalysisConfig(ValueError):
    pass


def normalize_analysis_config(expected_features: Any, cv_config: Any) -> tuple[dict, dict]:
    if expected_features is None:
        expected_features = {}
    if not isinstance(expected_features, dict):
        raise InvalidAnalysisConfig("expected_features must be an object")
    if cv_config is None:
        cv_config = {}
    if not isinstance(cv_config, dict):
        raise InvalidAnalysisConfig("cv_config must be an object")
    analyzers = cv_config.get("analyzers", [])
    if not isinstance(analyzers, list):
        raise InvalidAnalysisConfig("cv_config.analyzers must be a list")
    clean_analyzers = []
    seen: set[str] = set()
    for index, analyzer in enumerate(analyzers):
        if not isinstance(analyzer, dict):
            raise InvalidAnalysisConfig(f"cv_config.analyzers[{index}] must be an object")
        name = analyzer.get("name")
        if name not in ALLOWED_ANALYZERS:
            raise InvalidAnalysisConfig(f"unsupported analyzer {name!r}")
        if name in seen:
            raise InvalidAnalysisConfig(f"duplicate analyzer {name!r}")
        params = analyzer.get("params", {})
        if not isinstance(params, dict):
            raise InvalidAnalysisConfig(f"params for {name!r} must be an object")
        seen.add(name)
        clean_analyzers.append({"name": name, "params": params})
    return dict(expected_features), {"analyzers": clean_analyzers} if clean_analyzers else {}


def set_detection_point_analysis_config(
    db: Session,
    detection_point_id: str,
    expected_features: Any,
    cv_config: Any,
    tenant_id: str = "default",
) -> QCDetectionPoint:
    point = db.query(QCDetectionPoint).filter_by(id=detection_point_id, tenant_id=tenant_id).first()
    if point is None:
        raise InvalidAnalysisConfig("detection point not found")
    already_published = db.query(QCPublishBundle.id).filter_by(
        tenant_id=tenant_id, standard_revision_id=point.standard_revision_id
    ).first()
    if already_published:
        raise InvalidAnalysisConfig(
            "analysis config changes judgment inputs after publish; create and qualify a new revision"
        )
    expected, config = normalize_analysis_config(expected_features, cv_config)
    point.expected_features_json = expected
    point.cv_config_json = config
    db.commit()
    db.refresh(point)
    return point


__all__ = [
    "ALLOWED_ANALYZERS", "InvalidAnalysisConfig", "normalize_analysis_config",
    "set_detection_point_analysis_config",
]
