from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: int | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


ANONYMOUS_PRINCIPAL = McpPrincipal()
_current_principal: ContextVar[McpPrincipal] = ContextVar(
    "nexgo_mcp_principal",
    default=ANONYMOUS_PRINCIPAL,
)


def get_mcp_principal() -> McpPrincipal:
    return _current_principal.get()


def set_mcp_principal(principal: McpPrincipal) -> Token[McpPrincipal]:
    return _current_principal.set(principal)


def reset_mcp_principal(token: Token[McpPrincipal]) -> None:
    _current_principal.reset(token)
