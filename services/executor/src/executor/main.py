"""The only service permitted to mutate cluster state.

Executes a remediation action only after a human has approved it via the
Discord bot. Never invoked directly by services/agent.
"""


def execute_approved_action(action_id: str) -> None:
    # TODO: verify approval record in Postgres, then apply the change
    raise NotImplementedError
