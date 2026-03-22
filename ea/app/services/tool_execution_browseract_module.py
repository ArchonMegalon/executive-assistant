from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_execution_browseract_registry import (
    register_builtin_browseract_crezlo_property_tour,
    register_builtin_browseract_gemini_web_generate,
    register_builtin_browseract_extract,
    register_builtin_browseract_inventory,
    register_builtin_browseract_ui_service_by_capability,
    register_builtin_browseract_chatplayground_audit,
    register_builtin_browseract_onemin_billing_usage,
    register_builtin_browseract_onemin_member_reconciliation,
    register_builtin_browseract_workflow_repair,
    register_builtin_browseract_workflow_spec,
)
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class BrowserActToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        connector_dispatch: ConnectorDispatchToolAdapter,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = BrowserActToolAdapter(
            connector_dispatch=connector_dispatch,
        )

    @property
    def live_extract(self):
        return self._adapter._live_extract

    @live_extract.setter
    def live_extract(self, handler) -> None:
        self._adapter._live_extract = handler

    @property
    def chatplayground_audit(self):
        return self._adapter._chatplayground_audit

    @chatplayground_audit.setter
    def chatplayground_audit(self, handler) -> None:
        self._adapter._chatplayground_audit = handler

    @property
    def gemini_web_generate(self):
        return self._adapter._gemini_web_generate

    @gemini_web_generate.setter
    def gemini_web_generate(self, handler) -> None:
        self._adapter._gemini_web_generate = handler

    @property
    def onemin_billing_usage(self):
        return self._adapter._onemin_billing_usage

    @onemin_billing_usage.setter
    def onemin_billing_usage(self, handler) -> None:
        self._adapter._onemin_billing_usage = handler

    @property
    def onemin_member_reconciliation(self):
        return self._adapter._onemin_member_reconciliation

    @onemin_member_reconciliation.setter
    def onemin_member_reconciliation(self, handler) -> None:
        self._adapter._onemin_member_reconciliation = handler

    @property
    def crezlo_property_tour(self):
        return self._adapter._crezlo_property_tour

    @crezlo_property_tour.setter
    def crezlo_property_tour(self, handler) -> None:
        self._adapter._crezlo_property_tour = handler

    @property
    def ui_service_callbacks(self) -> dict[str, object]:
        return self._adapter._ui_service_callbacks

    def register_extract(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_extract(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_inventory(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_inventory(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_workflow_spec(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_workflow_spec(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_workflow_repair(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_workflow_repair(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_chatplayground_audit(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_chatplayground_audit(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_gemini_web_generate(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_gemini_web_generate(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_onemin_billing_usage(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_onemin_billing_usage(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_onemin_member_reconciliation(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_onemin_member_reconciliation(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_crezlo_property_tour(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_crezlo_property_tour(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_ui_service(
        self,
        register_handler: Callable[[str, ToolExecutionHandler], None],
        *,
        capability_key: str,
    ) -> None:
        register_builtin_browseract_ui_service_by_capability(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
            capability_key=capability_key,
        )
