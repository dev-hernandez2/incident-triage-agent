"""discord.py UI: the Approve/Reject buttons attached to an executable
finding's embed, and the reason modal shown on Reject.
"""

import uuid
from collections.abc import Callable

import discord
from db.models import Action
from sqlalchemy.orm import Session

from bot.actions import approve_action, reject_action


def _member_has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def _load_action(session: Session, action_id: str) -> Action:
    # action_id arrives as a str (Discord interaction/custom_id data is all
    # strings); session.get needs an actual uuid.UUID for the PK lookup to
    # bind correctly against the UUID column.
    action = session.get(Action, uuid.UUID(action_id))
    assert action is not None
    return action


class RejectReasonModal(discord.ui.Modal, title="Reject remediation"):
    reason: discord.ui.TextInput["RejectReasonModal"] = discord.ui.TextInput(
        label="Reason", style=discord.TextStyle.paragraph
    )

    def __init__(self, session: Session, action_id: str, approver_role_id: int) -> None:
        super().__init__()
        self._session = session
        self._action_id = action_id
        self._approver_role_id = approver_role_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        action = _load_action(self._session, self._action_id)
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        result = reject_action(
            self._session,
            action,
            rejecter_id=str(interaction.user.id),
            reason=str(self.reason.value),
            has_role=has_role,
        )
        self._session.commit()

        if result == "forbidden":
            await interaction.response.send_message(
                "You don't have permission to reject this action.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Rejected: {self.reason.value}", ephemeral=True)


class RemediationView(discord.ui.View):
    def __init__(
        self,
        session: Session,
        action_id: str,
        approver_role_id: int,
        approver: Callable[[str], None],
    ) -> None:
        super().__init__(timeout=None)
        self._session = session
        self._action_id = action_id
        self._approver_role_id = approver_role_id
        self._approver = approver

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(
        self, interaction: discord.Interaction, button: "discord.ui.Button[RemediationView]"
    ) -> None:
        await self.approve_callback(interaction)

    async def approve_callback(self, interaction: discord.Interaction) -> None:
        action = _load_action(self._session, self._action_id)
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        result = approve_action(
            self._session, action, approver_id=str(interaction.user.id), has_role=has_role
        )
        self._session.commit()

        if result == "forbidden":
            await interaction.response.send_message(
                "You don't have permission to approve this action.", ephemeral=True
            )
            return
        if result == "already_decided":
            await interaction.response.send_message(
                "This action was already decided.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content=f"Approved by <@{interaction.user.id}>", view=None
        )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
    async def reject(
        self, interaction: discord.Interaction, button: "discord.ui.Button[RemediationView]"
    ) -> None:
        _load_action(self._session, self._action_id)
        has_role = _member_has_role(interaction.user, self._approver_role_id)  # type: ignore[arg-type]
        if not has_role:
            await interaction.response.send_message(
                "You don't have permission to reject this action.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            RejectReasonModal(self._session, self._action_id, self._approver_role_id)
        )
