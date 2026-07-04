"""S3/S4 tables: bundles, workstations, assignments, pad submissions, verdicts

Creates real migrations for the tables that shipped in S3 (bundle/workstation
management) and S4 (server verdict recomputation). These previously existed only
via ``Base.metadata.create_all`` (test-only); this migration makes a production
``alembic upgrade`` provision them. Schema mirrors ``src.db.qc_bundle_models``
and ``src.db.qc_verdict_models`` exactly.

Idempotent / adoptive: a deployment that already ran with ``create_all`` will
have these tables. For each table we therefore:

  1. check whether it already exists;
  2. if it exists, verify its columns match what this migration creates;
  3. if compatible, adopt it (do not re-create) so ``upgrade head`` succeeds;
  4. if incompatible, fail with a clear remediation message rather than leave a
     silently-diverged schema.

Revision ID: 018
Revises: 017
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


# ── Table builders ────────────────────────────────────────────────────────────


def _create_qc_bundles() -> None:
    op.create_table(
        'qc_bundles',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('bundle_version', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='signed'),
        sa.Column('sku_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('standard_revision_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('manifest_sha256', sa.String(length=64), nullable=False),
        sa.Column('signature', sa.String(length=256), nullable=False),
        sa.Column('signature_algo', sa.String(length=32), nullable=False, server_default='hmac-sha256'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'bundle_version', name='uq_bundle_tenant_version'),
    )
    op.create_index('ix_qc_bundles_tenant_id', 'qc_bundles', ['tenant_id'])
    op.create_index('ix_qc_bundles_bundle_version', 'qc_bundles', ['bundle_version'])


def _create_qc_workstations() -> None:
    op.create_table(
        'qc_workstations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('workstation_id', sa.String(length=128), nullable=False),
        sa.Column('display_name', sa.String(length=256), nullable=False),
        sa.Column('site_or_line', sa.String(length=256), nullable=True),
        sa.Column('paired_status', sa.String(length=32), nullable=False, server_default='unpaired'),
        sa.Column('assigned_bundle_version', sa.String(length=64), nullable=True),
        sa.Column('installed_bundle_version', sa.String(length=64), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(length=64), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('pairing_token', sa.String(length=128), nullable=True),
        sa.Column('outbox_upload_status', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'workstation_id', name='uq_workstation_tenant_id'),
    )
    op.create_index('ix_qc_workstations_tenant_id', 'qc_workstations', ['tenant_id'])
    op.create_index('ix_qc_workstations_workstation_id', 'qc_workstations', ['workstation_id'])


def _create_qc_bundle_assignments() -> None:
    op.create_table(
        'qc_bundle_assignments',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('workstation_pk', sa.String(length=64), nullable=False),
        sa.Column('bundle_pk', sa.String(length=64), nullable=False),
        sa.Column('bundle_version', sa.String(length=64), nullable=False),
        sa.Column('assigned_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['workstation_pk'], ['qc_workstations.id']),
        sa.ForeignKeyConstraint(['bundle_pk'], ['qc_bundles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_bundle_assignments_tenant_id', 'qc_bundle_assignments', ['tenant_id'])
    op.create_index('ix_qc_bundle_assignments_workstation_pk', 'qc_bundle_assignments', ['workstation_pk'])
    op.create_index('ix_qc_bundle_assignments_bundle_pk', 'qc_bundle_assignments', ['bundle_pk'])


def _create_qc_pad_submissions() -> None:
    op.create_table(
        'qc_pad_submissions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('job_ref', sa.String(length=128), nullable=False),
        sa.Column('standard_revision_id', sa.String(length=64), nullable=False),
        sa.Column('bundle_version', sa.String(length=64), nullable=True),
        sa.Column('workstation_id', sa.String(length=128), nullable=True),
        sa.Column('pad_overall_result', sa.String(length=32), nullable=False),
        sa.Column('raw_json', sa.JSON(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_pad_submissions_tenant_id', 'qc_pad_submissions', ['tenant_id'])
    op.create_index('ix_qc_pad_submissions_job_ref', 'qc_pad_submissions', ['job_ref'])
    op.create_index('ix_qc_pad_submissions_standard_revision_id', 'qc_pad_submissions', ['standard_revision_id'])
    op.create_index('ix_qc_pad_submissions_workstation_id', 'qc_pad_submissions', ['workstation_id'])


def _create_qc_submitted_checkpoints() -> None:
    op.create_table(
        'qc_submitted_checkpoints',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('submission_id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('checkpoint_id', sa.String(length=128), nullable=False),
        sa.Column('result', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['submission_id'], ['qc_pad_submissions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_submitted_checkpoints_submission_id', 'qc_submitted_checkpoints', ['submission_id'])
    op.create_index('ix_qc_submitted_checkpoints_tenant_id', 'qc_submitted_checkpoints', ['tenant_id'])


def _create_qc_server_verdicts() -> None:
    op.create_table(
        'qc_server_verdicts',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('submission_id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('server_overall_result', sa.String(length=32), nullable=False),
        sa.Column('pad_overall_result', sa.String(length=32), nullable=False),
        sa.Column('agrees', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('review_required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('rule_applied', sa.String(length=64), nullable=False),
        sa.Column('standard_revision_id', sa.String(length=64), nullable=False),
        sa.Column('bundle_version', sa.String(length=64), nullable=True),
        sa.Column('missing_checkpoints_json', sa.JSON(), nullable=True),
        sa.Column('failing_checkpoints_json', sa.JSON(), nullable=True),
        sa.Column('warnings_json', sa.JSON(), nullable=True),
        sa.Column('differences_json', sa.JSON(), nullable=True),
        sa.Column('human_final_decision', sa.String(length=32), nullable=True),
        sa.Column('human_decided_by', sa.String(length=128), nullable=True),
        sa.Column('human_decision_comment', sa.Text(), nullable=True),
        sa.Column('human_decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recomputed_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['submission_id'], ['qc_pad_submissions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_server_verdicts_submission_id', 'qc_server_verdicts',
                    ['submission_id'], unique=True)
    op.create_index('ix_qc_server_verdicts_tenant_id', 'qc_server_verdicts', ['tenant_id'])


# tablename -> (builder, expected column-name set). The expected columns are the
# columns this migration creates, which equal the ORM model columns (the same
# ones create_all would have made) — so an adopted create_all table matches.
_TABLES = [
    ('qc_bundles', _create_qc_bundles, {
        'id', 'tenant_id', 'bundle_version', 'status', 'sku_count',
        'standard_revision_count', 'created_by', 'manifest_json', 'manifest_sha256',
        'signature', 'signature_algo', 'created_at',
    }),
    ('qc_workstations', _create_qc_workstations, {
        'id', 'tenant_id', 'workstation_id', 'display_name', 'site_or_line',
        'paired_status', 'assigned_bundle_version', 'installed_bundle_version',
        'last_seen_at', 'last_sync_status', 'last_error', 'pairing_token',
        'outbox_upload_status', 'created_at', 'updated_at',
    }),
    ('qc_bundle_assignments', _create_qc_bundle_assignments, {
        'id', 'tenant_id', 'workstation_pk', 'bundle_pk', 'bundle_version',
        'assigned_by', 'created_at',
    }),
    ('qc_pad_submissions', _create_qc_pad_submissions, {
        'id', 'tenant_id', 'job_ref', 'standard_revision_id', 'bundle_version',
        'workstation_id', 'pad_overall_result', 'raw_json', 'submitted_at',
    }),
    ('qc_submitted_checkpoints', _create_qc_submitted_checkpoints, {
        'id', 'submission_id', 'tenant_id', 'checkpoint_id', 'result',
    }),
    ('qc_server_verdicts', _create_qc_server_verdicts, {
        'id', 'submission_id', 'tenant_id', 'server_overall_result',
        'pad_overall_result', 'agrees', 'review_required', 'rule_applied',
        'standard_revision_id', 'bundle_version', 'missing_checkpoints_json',
        'failing_checkpoints_json', 'warnings_json', 'differences_json',
        'human_final_decision', 'human_decided_by', 'human_decision_comment',
        'human_decided_at', 'recomputed_at',
    }),
]


def _ensure_table(name: str, build, expected_cols: set) -> None:
    """Create the table, or adopt a compatible pre-existing one, or fail clearly."""
    insp = sa.inspect(op.get_bind())  # fresh inspector each call — reflects prior creates
    if name not in insp.get_table_names():
        build()
        return

    actual_cols = {c["name"] for c in insp.get_columns(name)}
    if actual_cols == expected_cols:
        return  # pre-existing (e.g. via create_all) and compatible → adopt

    missing = sorted(expected_cols - actual_cols)
    unexpected = sorted(actual_cols - expected_cols)
    raise RuntimeError(
        f"Cannot upgrade to 018: table '{name}' already exists but its schema is "
        f"incompatible with the model this migration creates "
        f"(missing columns={missing}, unexpected columns={unexpected}). "
        f"Remediation: align '{name}' to src.db.qc_bundle_models / "
        f"src.db.qc_verdict_models (add the missing columns), or drop the table if "
        f"it holds no data, then re-run `alembic upgrade head`."
    )


def upgrade() -> None:
    # Dependency order: parents (bundles, workstations, pad_submissions) before
    # children (assignments, checkpoints, verdicts).
    for name, build, expected_cols in _TABLES:
        _ensure_table(name, build, expected_cols)


def downgrade() -> None:
    op.drop_index('ix_qc_server_verdicts_tenant_id', table_name='qc_server_verdicts')
    op.drop_index('ix_qc_server_verdicts_submission_id', table_name='qc_server_verdicts')
    op.drop_table('qc_server_verdicts')

    op.drop_index('ix_qc_submitted_checkpoints_tenant_id', table_name='qc_submitted_checkpoints')
    op.drop_index('ix_qc_submitted_checkpoints_submission_id', table_name='qc_submitted_checkpoints')
    op.drop_table('qc_submitted_checkpoints')

    op.drop_index('ix_qc_pad_submissions_workstation_id', table_name='qc_pad_submissions')
    op.drop_index('ix_qc_pad_submissions_standard_revision_id', table_name='qc_pad_submissions')
    op.drop_index('ix_qc_pad_submissions_job_ref', table_name='qc_pad_submissions')
    op.drop_index('ix_qc_pad_submissions_tenant_id', table_name='qc_pad_submissions')
    op.drop_table('qc_pad_submissions')

    op.drop_index('ix_qc_bundle_assignments_bundle_pk', table_name='qc_bundle_assignments')
    op.drop_index('ix_qc_bundle_assignments_workstation_pk', table_name='qc_bundle_assignments')
    op.drop_index('ix_qc_bundle_assignments_tenant_id', table_name='qc_bundle_assignments')
    op.drop_table('qc_bundle_assignments')

    op.drop_index('ix_qc_workstations_workstation_id', table_name='qc_workstations')
    op.drop_index('ix_qc_workstations_tenant_id', table_name='qc_workstations')
    op.drop_table('qc_workstations')

    op.drop_index('ix_qc_bundles_bundle_version', table_name='qc_bundles')
    op.drop_index('ix_qc_bundles_tenant_id', table_name='qc_bundles')
    op.drop_table('qc_bundles')
