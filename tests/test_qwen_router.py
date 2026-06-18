"""Tests for the QWEN QC Router."""
from __future__ import annotations

import pytest

from src.qwen.fake_providers import (
    FakeCloudQwenProvider,
    FailingQwenProvider,
    TimeoutQwenProvider,
)
from src.qwen.router import QwenRouter
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
)


@pytest.fixture
def router():
    return QwenRouter()


@pytest.fixture
def standard_photos():
    return []


@pytest.fixture
def captured_photo():
    return CapturePhotoInput(photo_id="cap_001", local_path="/tmp/cap.jpg")


@pytest.fixture
def qc_points():
    return [
        QcPointInput(
            qc_point_id="qp_001",
            qc_point_code="COLOR",
            name="Color Check",
            description="Check color matches",
        ),
        QcPointInput(
            qc_point_id="qp_002",
            qc_point_code="LABEL",
            name="Label Check",
            description="Check label is present",
        ),
    ]


@pytest.fixture
def context():
    return InspectionContext(
        tenant_id="tenant_test",
        sku_id="SKU-001",
        standard_id="std_001",
        inspection_id="insp_001",
    )


class TestCloudProviderRouting:
    def test_valid_result_accepted_with_fake_cloud(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        provider = FakeCloudQwenProvider()
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=provider,
        )
        assert isinstance(result, QwenInspectionOutput)
        assert result.overall_result == "pass"
        assert result.engine == "fake_cloud_qwen"
        assert len(result.items) == len(qc_points)

    def test_all_items_pass_with_fake_cloud(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FakeCloudQwenProvider(),
        )
        for item in result.items:
            assert item.result == "pass"


class TestCloudDisabled:
    def test_cloud_disabled_returns_review_required(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FakeCloudQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_cloud_disabled_all_items_review_required(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FakeCloudQwenProvider(),
        )
        for item in result.items:
            assert item.result == "review_required"

    def test_no_provider_returns_review_required(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=None,
        )
        assert result.overall_result == "review_required"


class TestProviderErrors:
    def test_failing_provider_returns_review_required(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FailingQwenProvider(),
        )
        assert result.overall_result == "review_required"
        assert result.fallback.used is True

    def test_failing_provider_does_not_propagate_exception(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        # Should NOT raise — router catches the exception
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FailingQwenProvider(),
        )
        assert isinstance(result, QwenInspectionOutput)

    def test_timeout_provider_returns_review_required(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=TimeoutQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_on_device_fail_does_not_become_cloud_pass(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        """A failing provider should NOT produce a 'pass' result."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FailingQwenProvider(),
        )
        assert result.overall_result != "pass"


class TestFallbackInfo:
    def test_review_required_has_fallback_info(
        self, router, standard_photos, captured_photo, qc_points, context, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=FakeCloudQwenProvider(),
        )
        assert result.fallback.used is True
        assert result.fallback.reason is not None
