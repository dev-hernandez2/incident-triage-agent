import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bot.views import RejectReasonModal, RemediationView
from db.models import Action, Base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _make_action(session: Session) -> Action:
    action = Action(
        incident_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="checkoutservice",
        replicas=5,
        reason="under load",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _fake_interaction(role_id: int | None, approver_role_id: int) -> SimpleNamespace:
    roles = [SimpleNamespace(id=role_id)] if role_id is not None else []
    member = SimpleNamespace(id=999, roles=roles)
    return SimpleNamespace(
        user=member,
        response=SimpleNamespace(
            send_message=AsyncMock(), edit_message=AsyncMock(), send_modal=AsyncMock()
        ),
        message=SimpleNamespace(edit=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_approve_button_without_role_sends_ephemeral_denial(session: Session) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=None, approver_role_id=42)

    await view.approve_callback(interaction)  # type: ignore[arg-type]

    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    session.refresh(action)
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_approve_button_with_role_approves_and_edits_message(session: Session) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=42, approver_role_id=42)

    await view.approve_callback(interaction)  # type: ignore[arg-type]

    session.refresh(action)
    assert action.status == "approved"
    interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_button_without_role_sends_ephemeral_denial_and_no_modal(
    session: Session,
) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=None, approver_role_id=42)

    await view.reject.callback(interaction)  # type: ignore[arg-type]

    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    interaction.response.send_modal.assert_not_called()
    session.refresh(action)
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_reject_button_with_role_opens_modal(session: Session) -> None:
    action = _make_action(session)
    view = RemediationView(
        session=session, action_id=str(action.id), approver_role_id=42, approver=lambda _: None
    )
    interaction = _fake_interaction(role_id=42, approver_role_id=42)

    await view.reject.callback(interaction)  # type: ignore[arg-type]

    interaction.response.send_modal.assert_awaited_once()
    interaction.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_reject_modal_without_role_sends_ephemeral_denial(session: Session) -> None:
    action = _make_action(session)
    modal = RejectReasonModal(session=session, action_id=str(action.id), approver_role_id=42)
    modal.reason._value = "too risky"
    interaction = _fake_interaction(role_id=None, approver_role_id=42)

    await modal.on_submit(interaction)  # type: ignore[arg-type]

    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    session.refresh(action)
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_reject_modal_with_role_rejects_with_reason(session: Session) -> None:
    action = _make_action(session)
    modal = RejectReasonModal(session=session, action_id=str(action.id), approver_role_id=42)
    modal.reason._value = "too risky"
    interaction = _fake_interaction(role_id=42, approver_role_id=42)

    await modal.on_submit(interaction)  # type: ignore[arg-type]

    session.refresh(action)
    assert action.status == "rejected"
    assert action.rejection_reason == "too risky"
    interaction.response.send_message.assert_awaited_once()
