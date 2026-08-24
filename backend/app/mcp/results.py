import base64
import binascii
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import uuid4

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from app.core.config import get_settings
from app.mcp.models import McpErrorPayload, McpToolEnvelope


logger = logging.getLogger(__name__)
McpResult = Annotated[CallToolResult, McpToolEnvelope]


class McpToolFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        fields: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields


class StructuredToolErrorMiddleware:
    async def __call__(self, context, call_next):
        try:
            result = await call_next(context)
        except ValidationError as exc:
            if context.method != "tools/call":
                raise
            return _validation_error_result(exc)

        if context.method != "tools/call":
            return result

        if isinstance(result, CallToolResult):
            is_error = result.is_error
            structured_content = result.structured_content
            error_text = " ".join(
                block.text
                for block in result.content
                if isinstance(block, TextContent)
            )
        elif isinstance(result, dict):
            is_error = bool(result.get("isError", result.get("is_error", False)))
            structured_content = result.get("structuredContent", result.get("structured_content"))
            error_text = " ".join(
                str(block.get("text", ""))
                for block in result.get("content", [])
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            return result

        if not is_error or structured_content is not None:
            return result
        if "validation error" in error_text.lower():
            return error_result("INVALID_ARGUMENT", "工具参数校验失败")
        if "unknown tool" in error_text.lower():
            return error_result("NOT_FOUND", "工具不存在")

        correlation_id = uuid4().hex
        logger.error("MCP SDK 返回未分类工具错误，correlation_id=%s", correlation_id)
        return error_result(
            "INTERNAL_ERROR",
            "服务器内部错误",
            correlation_id=correlation_id,
        )


def decode_package_base64(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise McpToolFailure("INVALID_ARGUMENT", "package_base64 不能为空")

    max_package_bytes = get_settings().mcp_max_package_bytes
    max_encoded_length = ((max_package_bytes + 2) // 3) * 4
    if len(value) > max_encoded_length:
        raise McpToolFailure(
            "PACKAGE_TOO_LARGE",
            "压缩包超过 MCP 传输上限，请改用 OpenAPI multipart 接口",
            fields={"max_package_bytes": max_package_bytes},
        )

    try:
        encoded = value.encode("ascii")
        content = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise McpToolFailure("INVALID_ARGUMENT", "package_base64 不是严格有效的 Base64") from exc

    if len(content) > max_package_bytes:
        raise McpToolFailure(
            "PACKAGE_TOO_LARGE",
            "压缩包超过 MCP 传输上限，请改用 OpenAPI multipart 接口",
            fields={"max_package_bytes": max_package_bytes},
        )
    return content


def success_result(data: Any, message: str) -> CallToolResult:
    envelope = McpToolEnvelope(ok=True, data=jsonable_encoder(data))
    return CallToolResult(
        content=[TextContent(text=message)],
        structuredContent=envelope.model_dump(mode="json", exclude_none=True),
    )


def error_result(
    code: str,
    message: str,
    *,
    fields: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> CallToolResult:
    envelope = McpToolEnvelope(
        ok=False,
        error=McpErrorPayload(
            code=code,
            message=message,
            fields=fields,
            correlation_id=correlation_id,
        ),
    )
    return CallToolResult(
        content=[TextContent(text=f"{code}: {message}")],
        structuredContent=envelope.model_dump(mode="json", exclude_none=True),
        isError=True,
    )


async def execute_tool(
    operation: Callable[[], Any | Awaitable[Any]],
    success_message: str,
) -> CallToolResult:
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        return success_result(result, success_message)
    except McpToolFailure as exc:
        return error_result(exc.code, exc.message, fields=exc.fields)
    except ValidationError as exc:
        return _validation_error_result(exc)
    except HTTPException as exc:
        return _http_exception_result(exc)
    except Exception:
        correlation_id = uuid4().hex
        logger.exception("MCP 工具执行失败，correlation_id=%s", correlation_id)
        return error_result(
            "INTERNAL_ERROR",
            "服务器内部错误",
            correlation_id=correlation_id,
        )


def _http_exception_result(exc: HTTPException) -> CallToolResult:
    detail = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return error_result("AUTHENTICATION_REQUIRED", detail)
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return error_result("NOT_FOUND", detail)
    if exc.status_code == status.HTTP_409_CONFLICT:
        return error_result("CONFLICT", detail)
    if exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
        return error_result("PACKAGE_TOO_LARGE", detail)
    if exc.status_code in {
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    }:
        fields = None if isinstance(exc.detail, str) else {"detail": jsonable_encoder(exc.detail)}
        return error_result("INVALID_ARGUMENT", detail, fields=fields)
    if exc.status_code in {
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        status.HTTP_504_GATEWAY_TIMEOUT,
    }:
        return error_result("UPSTREAM_ERROR", "上游服务暂不可用")

    correlation_id = uuid4().hex
    logger.error(
        "MCP 工具收到未分类 HTTP 错误，status_code=%s correlation_id=%s",
        exc.status_code,
        correlation_id,
    )
    return error_result(
        "INTERNAL_ERROR",
        "服务器内部错误",
        correlation_id=correlation_id,
    )


def _validation_error_result(exc: ValidationError) -> CallToolResult:
    fields = {
        "validation_errors": [
            {
                "location": list(error.get("loc", ())),
                "message": error.get("msg", "参数无效"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors(include_input=False, include_url=False)
        ]
    }
    return error_result("INVALID_ARGUMENT", "工具参数校验失败", fields=fields)
