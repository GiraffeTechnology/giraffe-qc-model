"""Server-side Jetson binding: provisioning, 1:1 pairing, re-pair fail-closed."""
from __future__ import annotations

import pytest

from src.db.qc_jetson_models import QCJetsonPairingEvent, QCJetsonRunner
from src.qc_model.jetson import constants as C
from src.qc_model.jetson import service
from src.qc_model.jetson.service import WorkstationNotFound

from tests.jetson_helpers import db_session, client, make_workstation  # noqa: F401


def _provision(db, device_id="jetson-1", fp="1111-2222-3333-4444"):
    return service.provision_runner(db, jetson_device_id=device_id, pubkey_fingerprint=fp)


def test_provision_is_idempotent(db_session):
    r1 = _provision(db_session)
    r2 = _provision(db_session)
    assert r1.id == r2.id
    assert db_session.query(QCJetsonRunner).count() == 1


def test_register_binding_requires_existing_workstation(db_session):
    _provision(db_session)
    with pytest.raises(WorkstationNotFound):
        service.register_binding(
            db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
            workstation_id="NOPE", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_USB,
        )


def test_register_binding_pairs_and_audits(db_session):
    make_workstation(db_session, "WS-1")
    _provision(db_session)
    runner = service.register_binding(
        db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
        workstation_id="WS-1", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_USB,
    )
    assert runner.pairing_status == C.PAIRING_PAIRED
    assert runner.paired_pad_device_id == "pad-1"
    assert runner.pairing_path == "usb"
    events = {e.event_type for e in db_session.query(QCJetsonPairingEvent).all()}
    assert C.EVENT_PAIRED in events


def test_auto_provision_on_binding_when_unseen(db_session):
    make_workstation(db_session, "WS-1")
    runner = service.register_binding(
        db_session, jetson_device_id="jetson-new", pubkey_fingerprint="fp",
        workstation_id="WS-1", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_WIFI,
    )
    assert runner.pairing_status == C.PAIRING_PAIRED


def test_repair_to_new_pad_replaces_binding_no_grace(db_session):
    make_workstation(db_session, "WS-1")
    _provision(db_session)
    service.register_binding(
        db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
        workstation_id="WS-1", pad_device_id="pad-OLD", pairing_path=C.PAIRING_PATH_USB,
    )
    runner = service.register_binding(
        db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
        workstation_id="WS-1", pad_device_id="pad-NEW", pairing_path=C.PAIRING_PATH_USB,
    )
    assert runner.paired_pad_device_id == "pad-NEW"
    events = [e.event_type for e in db_session.query(QCJetsonPairingEvent).order_by(QCJetsonPairingEvent.created_at).all()]
    assert C.EVENT_REPAIRED in events


def test_workstation_rebind_unbinds_other_jetson(db_session):
    make_workstation(db_session, "WS-1")
    service.provision_runner(db_session, jetson_device_id="jetson-A", pubkey_fingerprint="a")
    service.provision_runner(db_session, jetson_device_id="jetson-B", pubkey_fingerprint="b")
    service.register_binding(
        db_session, jetson_device_id="jetson-A", pubkey_fingerprint="a",
        workstation_id="WS-1", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_USB,
    )
    # Bind a different Jetson to the SAME workstation → the first must be freed.
    service.register_binding(
        db_session, jetson_device_id="jetson-B", pubkey_fingerprint="b",
        workstation_id="WS-1", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_USB,
    )
    a = service.get_runner(db_session, "default", "jetson-A")
    b = service.get_runner(db_session, "default", "jetson-B")
    assert a.pairing_status == C.PAIRING_UNPAIRED and a.workstation_pk is None
    assert b.pairing_status == C.PAIRING_PAIRED


def test_unpair_is_fail_closed(db_session):
    make_workstation(db_session, "WS-1")
    _provision(db_session)
    service.register_binding(
        db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
        workstation_id="WS-1", pad_device_id="pad-1", pairing_path=C.PAIRING_PATH_USB,
    )
    runner = service.unpair(db_session, jetson_device_id="jetson-1")
    assert runner.pairing_status == C.PAIRING_UNPAIRED
    assert runner.paired_pad_device_id is None


def test_invalid_pairing_path_rejected(db_session):
    make_workstation(db_session, "WS-1")
    _provision(db_session)
    with pytest.raises(ValueError):
        service.register_binding(
            db_session, jetson_device_id="jetson-1", pubkey_fingerprint="fp",
            workstation_id="WS-1", pad_device_id="pad-1", pairing_path="bluetooth",
        )
