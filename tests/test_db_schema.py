"""DB schema integrity tests — run against in-memory SQLite."""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, SampleItem, QCTask, QCResult, VideoTask, CaptureRecord


@pytest.fixture(scope="module")
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_all_five_tables_exist(db_session):
    inspector = inspect(db_session.get_bind())
    tables = set(inspector.get_table_names())
    assert {"sample_items", "qc_tasks", "qc_results", "video_tasks", "capture_records"}.issubset(tables)


def test_video_tasks_has_pipeline_stats_columns(db_session):
    inspector = inspect(db_session.get_bind())
    cols = {c["name"] for c in inspector.get_columns("video_tasks")}
    for col in ("total_frames", "tier1_filtered", "tier2_processed", "tier2_passed", "tier3_llm_called", "llm_save_ratio"):
        assert col in cols, f"Missing column: {col}"


def test_insert_sample_and_query(db_session):
    from datetime import datetime, timezone
    item = SampleItem(sku_id="TEST-SKU", image_path="/tmp/test.png", uploaded_at=datetime.now(timezone.utc))
    db_session.add(item)
    db_session.commit()
    found = db_session.query(SampleItem).filter_by(sku_id="TEST-SKU").first()
    assert found is not None
    assert found.is_active is True


def test_foreign_key_task_references_sample(db_session):
    from datetime import datetime, timezone
    sample = db_session.query(SampleItem).first()
    task = QCTask(
        sample_id=sample.id,
        source_image_path="/tmp/prod.png",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    db_session.commit()
    assert task.id is not None
    assert task.status == "pending"


def test_qc_result_links_to_task(db_session):
    from datetime import datetime, timezone
    task = db_session.query(QCTask).first()
    result = QCResult(
        task_id=task.id,
        llm_provider="mock",
        model_name="mock-v1",
        http_status=200,
        elapsed_ms=1,
        overall_result="pass",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(result)
    db_session.commit()
    assert result.id is not None
