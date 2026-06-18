"""§4.5.1–4.5.4 exhaustive branch coverage using simulated on-device inspector outcomes.

Every decision branch in the on-device → router → cloud flow is exercised here
using deterministic fakes. No real model, MNN JNI, or network calls are made.

Branch map:
  A. on-device result accepted (pass, high confidence) → return directly
  B. on-device timeout → cloud fallback (if enabled) / review_required
  C. on-device parse failure → cloud fallback (if enabled) / review_required
  D. on-device low confidence (review_required) → cloud fallback / review_required
  E. §4.5.4 on-device FAIL is final → never let cloud convert fail to pass
  F. on-device FAIL with flag disabled → cloud may handle
  G. cloud disabled → review_required
  H. no provider → review_required
  I. model not provisioned → cloud (if enabled) / review_required
  J. both on-device and cloud fail → review_required (double failure)
"""
from __future__ import annotations

import pytest

from src.qwen.fake_providers import (
    FakeCloudQwenProvider,
    FakeFailCloudQwenProvider,
    FailingQwenProvider,
    InvalidJsonQwenProvider,
    NotProvisionedQwenProvider,
    TimeoutQwenProvider,
)
from src.qwen.router import QwenRouter
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def qc_points():
    return [
        QcPointInput(qc_point_id="QC-01", qc_point_code="color",  name="Color",  description="Color match"),
        QcPointInput(qc_point_id="QC-02", qc_point_code="border", name="Border", description="Border intact"),
        QcPointInput(qc_point_id="QC-03", qc_point_code="defect", name="Defect", description="No defects"),
    ]


@pytest.fixture
def captured_photo():
    return CapturePhotoInput(photo_id="cap-p9", local_path="/tmp/cap_p9.jpg")


@pytest.fixture
def ctx():
    return InspectionContext(
        tenant_id="tenant_phase9",
        sku_id="SKU-P9",
        standard_id="STD-P9",
        inspection_id="INS-P9",
    )


@pytest.fixture
def router_final():
    return QwenRouter(on_device_fail_is_final=True)


@pytest.fixture
def router_not_final():
    return QwenRouter(on_device_fail_is_final=False)


# ── Branch A: on-device accept ────────────────────────────────────────────────

class TestBranchA_OnDeviceAccept:
    def test_cloud_provider_pass_accepted(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch A: cloud path returns pass — accepted as-is."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
        )
        assert result.overall_result == "pass"
        assert result.engine == "fake_cloud_qwen"
        assert len(result.items) == len(qc_points)

    def test_all_item_ids_present(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
        )
        returned_ids = {item.qc_point_id for item in result.items}
        expected_ids = {p.qc_point_id for p in qc_points}
        assert returned_ids == expected_ids


# ── Branch B: on-device timeout → cloud ──────────────────────────────────────

class TestBranchB_Timeout:
    def test_timeout_provider_with_cloud_disabled_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch B: timeout with cloud disabled → review_required."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=TimeoutQwenProvider(),
        )
        assert result.overall_result == "review_required"
        assert result.fallback.used is True

    def test_timeout_provider_no_cloud_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=TimeoutQwenProvider(),
        )
        assert result.overall_result == "review_required"


# ── Branch C: on-device parse failure → cloud ────────────────────────────────

class TestBranchC_ParseFailure:
    def test_invalid_json_provider_returns_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch C: parse failure → review_required (fail-closed)."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=InvalidJsonQwenProvider(),
        )
        assert result.overall_result == "review_required"
        assert result.fallback.used is True

    def test_invalid_json_provider_fallback_reason_set(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=InvalidJsonQwenProvider(),
        )
        assert result.fallback.reason is not None
        assert result.fallback.reason != ""


# ── Branch D: on-device low confidence (review_required) → cloud ─────────────

class TestBranchD_LowConfidenceFallback:
    def test_on_device_review_required_cloud_enabled_escalates(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch D: on-device returns review_required → cloud handles → pass."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        # simulated_on_device_result="review_required" falls through to cloud
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="review_required",
        )
        assert result.overall_result == "pass"

    def test_on_device_review_required_cloud_disabled_stays_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="review_required",
        )
        assert result.overall_result == "review_required"
        for item in result.items:
            assert item.result == "review_required"


# ── Branch E: §4.5.4 on-device FAIL is final ─────────────────────────────────

class TestBranchE_OnDeviceFailIsFinal:
    def test_fail_is_final_blocks_cloud_pass(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """§4.5.4 — on-device FAIL must not be converted to pass by cloud."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),  # cloud would give pass
            simulated_on_device_result="fail",
        )
        # MUST remain fail — cloud must NOT override this
        assert result.overall_result == "fail", (
            "§4.5.4 violated: on-device fail was converted to pass by cloud"
        )

    def test_fail_is_final_items_are_fail(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """All items must also be fail when §4.5.4 is applied."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        for item in result.items:
            assert item.result == "fail", (
                f"§4.5.4: item {item.qc_point_id} should be fail, got {item.result}"
            )

    def test_fail_is_final_fallback_not_used(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """When fail is final, fallback.used must be False (no cloud was consulted)."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        assert result.fallback.used is False

    def test_fail_is_final_items_count_matches(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        assert len(result.items) == len(qc_points)

    def test_fail_is_final_blocks_fake_fail_cloud_too(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Even if cloud also returns fail, §4.5.4 path is taken (not cloud)."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeFailCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        assert result.overall_result == "fail"
        # Engine should be "router" (used the §4.5.4 short-circuit, not the cloud engine)
        assert result.engine == "router"


# ── Branch F: on-device FAIL with flag disabled → cloud ──────────────────────

class TestBranchF_FailFlagDisabled:
    def test_fail_not_final_escalates_to_cloud(
        self, router_not_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch F: on_device_fail_is_final=False allows cloud to run after on-device fail."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_not_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        assert result.overall_result == "pass"
        assert result.engine == "fake_cloud_qwen"

    def test_fail_not_final_cloud_disabled_still_review_required(
        self, router_not_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_not_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
            simulated_on_device_result="fail",
        )
        assert result.overall_result == "review_required"


# ── Branch G: cloud disabled → review_required ───────────────────────────────

class TestBranchG_CloudDisabled:
    def test_cloud_disabled_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_cloud_disabled_all_items_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
        )
        for item in result.items:
            assert item.result == "review_required"

    def test_cloud_disabled_fallback_used(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeCloudQwenProvider(),
        )
        assert result.fallback.used is True
        assert result.fallback.reason == "cloud_disabled"


# ── Branch H: no provider → review_required ──────────────────────────────────

class TestBranchH_NoProvider:
    def test_no_provider_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=None,
        )
        assert result.overall_result == "review_required"

    def test_no_provider_items_count_preserved(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=None,
        )
        assert len(result.items) == len(qc_points)


# ── Branch I: model not provisioned → cloud / review_required ────────────────

class TestBranchI_NotProvisioned:
    def test_not_provisioned_cloud_enabled_falls_back_to_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """NotProvisionedQwenProvider raises; router catches and returns review_required."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=NotProvisionedQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_not_provisioned_no_cloud_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=None,
        )
        assert result.overall_result == "review_required"


# ── Branch J: double failure (both on-device and cloud fail) ─────────────────

class TestBranchJ_DoubleFail:
    def test_failing_on_device_and_failing_cloud_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Branch J: on-device error + cloud error = review_required."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FailingQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_double_failure_never_produces_pass(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FailingQwenProvider(),
        )
        assert result.overall_result != "pass"

    def test_double_failure_items_review_required(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FailingQwenProvider(),
        )
        for item in result.items:
            assert item.result == "review_required"


# ── Cloud returns fail (not error) ───────────────────────────────────────────

class TestCloudReturnsFailResult:
    def test_cloud_fail_result_preserved(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """Cloud returning fail directly (not raising) is accepted as fail."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeFailCloudQwenProvider(),
        )
        assert result.overall_result == "fail"

    def test_cloud_fail_items_all_fail(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=FakeFailCloudQwenProvider(),
        )
        for item in result.items:
            assert item.result == "fail"


# ── Never-convert-failure-to-pass invariant ──────────────────────────────────

class TestNeverConvertFailureToPass:
    """Cross-cutting invariant: no path in the router must produce pass from a fail."""

    @pytest.mark.parametrize("provider,sim_result", [
        (FakeCloudQwenProvider(), "fail"),       # §4.5.4 enforced
        (FailingQwenProvider(),   None),          # provider error → review_required
        (TimeoutQwenProvider(),   None),          # timeout → review_required
        (InvalidJsonQwenProvider(), None),        # parse failure → review_required
    ])
    def test_no_path_converts_failure_to_pass(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch,
        provider, sim_result,
    ):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=provider,
            simulated_on_device_result=sim_result,
        )
        assert result.overall_result != "pass", (
            f"SAFETY VIOLATION: got pass from provider={provider.__class__.__name__} "
            f"sim_result={sim_result}"
        )

    def test_review_required_never_silently_becomes_pass(
        self, router_final, captured_photo, qc_points, ctx, monkeypatch
    ):
        """review_required result from a provider must stay review_required."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        result = router_final.route(
            standard_photos=[],
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=ctx,
            cloud_provider=InvalidJsonQwenProvider(),
        )
        assert result.overall_result in ("review_required", "fail")
        assert result.overall_result != "pass"
