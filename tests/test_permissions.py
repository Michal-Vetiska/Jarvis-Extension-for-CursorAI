from jarvis.tools.permissions import PermissionLevel, requires_confirmation
from jarvis.tools.base import ToolRegistry, ToolSpec
from pydantic import BaseModel


class In(BaseModel):
    x: int = 1


def test_confirmation_levels():
    assert not requires_confirmation(PermissionLevel.READ_ONLY)
    assert not requires_confirmation(PermissionLevel.LOCAL_UI_ACTION)
    assert requires_confirmation(PermissionLevel.PROJECT_MODIFICATION)
    assert requires_confirmation(PermissionLevel.PROCESS_EXECUTION)
    assert requires_confirmation(PermissionLevel.DESTRUCTIVE_ACTION)
    assert requires_confirmation(PermissionLevel.EXTERNAL_ACTION)


def test_tool_registry_blocks_unconfirmed():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="danger",
            description="x",
            permission=PermissionLevel.DESTRUCTIVE_ACTION,
            input_model=In,
            result_model=None,
            handler=lambda p: {"ok": True},
        )
    )
    blocked = reg.execute("danger", {}, confirmed=False)
    assert blocked.needs_confirmation
    assert not blocked.ok
    allowed = reg.execute("danger", {}, confirmed=True)
    assert allowed.ok
