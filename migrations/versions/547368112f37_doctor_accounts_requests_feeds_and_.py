"""doctor accounts, requests, feeds and carried-forward fairness

Revision ID: 547368112f37
Revises: 8cc9e409f79b
Create Date: 2026-08-15 02:19:44.562506
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '547368112f37'
down_revision = '8cc9e409f79b'
branch_labels = None
depends_on = None

# Two tables share this type, so it is created once by hand rather than left to
# the first CREATE TABLE — otherwise the second one fails on "type exists".
REQUEST_STATUS = ('pending', 'approved', 'declined', 'withdrawn')


def _status_column():
    return postgresql.ENUM(*REQUEST_STATUS, name='request_status', create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    sa.Enum(*REQUEST_STATUS, name='request_status').create(bind, checkfirst=True)

    op.create_table(
        'time_off_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('department_id', sa.Uuid(), nullable=False),
        sa.Column('doctor_id', sa.Uuid(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=200), nullable=True),
        sa.Column('status', _status_column(), nullable=False),
        sa.Column('decided_by', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.String(length=400), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_time_off_requests_department_id'), 'time_off_requests',
                    ['department_id'], unique=False)
    op.create_index(op.f('ix_time_off_requests_doctor_id'), 'time_off_requests',
                    ['doctor_id'], unique=False)

    op.create_table(
        'swap_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('department_id', sa.Uuid(), nullable=False),
        sa.Column('schedule_id', sa.Uuid(), nullable=False),
        sa.Column('from_doctor_id', sa.Uuid(), nullable=False),
        sa.Column('to_doctor_id', sa.Uuid(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('message', sa.String(length=400), nullable=True),
        sa.Column('status', _status_column(), nullable=False),
        sa.Column('decided_by', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.String(length=400), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['schedule_id'], ['schedules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_swap_requests_department_id'), 'swap_requests',
                    ['department_id'], unique=False)
    op.create_index(op.f('ix_swap_requests_from_doctor_id'), 'swap_requests',
                    ['from_doctor_id'], unique=False)
    op.create_index(op.f('ix_swap_requests_schedule_id'), 'swap_requests',
                    ['schedule_id'], unique=False)
    op.create_index(op.f('ix_swap_requests_to_doctor_id'), 'swap_requests',
                    ['to_doctor_id'], unique=False)

    op.create_table(
        'calendar_feeds',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('department_id', sa.Uuid(), nullable=False),
        sa.Column('doctor_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reads', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_calendar_feeds_department_id'), 'calendar_feeds',
                    ['department_id'], unique=False)
    op.create_index(op.f('ix_calendar_feeds_doctor_id'), 'calendar_feeds',
                    ['doctor_id'], unique=False)
    op.create_index(op.f('ix_calendar_feeds_token_hash'), 'calendar_feeds',
                    ['token_hash'], unique=True)

    op.add_column('invitations', sa.Column('doctor_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_invitations_doctor_id', 'invitations', 'doctors', ['doctor_id'], ['id'],
        ondelete='SET NULL',
    )

    # Existing rows need a value before the column can be NOT NULL, so the
    # default is set on the server and then dropped: new rows get it from the
    # model, and the database is not left carrying application defaults.
    op.add_column(
        'users',
        sa.Column('locale', sa.String(length=8), nullable=False, server_default='en'),
    )
    op.alter_column('users', 'locale', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'locale')
    op.drop_constraint('fk_invitations_doctor_id', 'invitations', type_='foreignkey')
    op.drop_column('invitations', 'doctor_id')

    op.drop_index(op.f('ix_calendar_feeds_token_hash'), table_name='calendar_feeds')
    op.drop_index(op.f('ix_calendar_feeds_doctor_id'), table_name='calendar_feeds')
    op.drop_index(op.f('ix_calendar_feeds_department_id'), table_name='calendar_feeds')
    op.drop_table('calendar_feeds')

    op.drop_index(op.f('ix_swap_requests_to_doctor_id'), table_name='swap_requests')
    op.drop_index(op.f('ix_swap_requests_schedule_id'), table_name='swap_requests')
    op.drop_index(op.f('ix_swap_requests_from_doctor_id'), table_name='swap_requests')
    op.drop_index(op.f('ix_swap_requests_department_id'), table_name='swap_requests')
    op.drop_table('swap_requests')

    op.drop_index(op.f('ix_time_off_requests_doctor_id'), table_name='time_off_requests')
    op.drop_index(op.f('ix_time_off_requests_department_id'), table_name='time_off_requests')
    op.drop_table('time_off_requests')

    sa.Enum(name='request_status').drop(op.get_bind(), checkfirst=True)
