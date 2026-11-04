"""JSON-lines provider codecs; executable, flags and authentication remain configured."""

import json

from app.core.exceptions import AdapterFailure, ResultValidationError, SetupFailure
from app.services.adapters.contract import AdapterRunInput, RunEvent
from app.services.runs.result import validate_result


class JSONLinesCodec:
    provider: str

    def prompt(self, provider: str, run_input: AdapterRunInput) -> bytes:
        run_input.validate_instructions()
        if provider != self.provider:
            raise SetupFailure("provider codec mismatch")
        instructions = run_input.instructions
        payload = {
            "job_objective": instructions.job_objective,
            "task_instructions": instructions.task_instructions,
            "spec_references": [json.loads(ref) for ref in instructions.spec_references],
            "context": run_input.context.model_dump(mode="json"),
            "execution_policy": run_input.execution_policy,
        }
        # The final response is treated as untrusted data and validated before use.
        request = (
            "Execute the task under the supplied context and policy. "
            "Return only a JSON object with schema_version, status, changed_files, "
            "test_results, findings, artifacts, and failure_info.\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        return request.encode("utf-8")

    def event(self, line: bytes) -> RunEvent:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("event must be an object")
            event_type = payload.get("type", "provider_output")
            if not isinstance(event_type, str):
                raise ValueError("event type must be a string")
            return RunEvent(event_type=event_type, payload=payload)
        except (ValueError, UnicodeDecodeError):
            raise AdapterFailure("provider emitted malformed JSON event") from None

    def result(self, events: list[RunEvent]) -> object:
        if any(event.event_type in {"error", "turn.failed", "runError"} for event in events):
            raise AdapterFailure("provider reported failure")
        for event in reversed(events):
            payload = event.payload
            item = payload.get("item")
            candidates = [payload.get("structured_result"), payload.get("result")]
            if isinstance(item, dict) and item.get("type") == "agent_message":
                candidates.append(item.get("text"))
            for value in candidates:
                try:
                    if isinstance(value, str):
                        value = json.loads(value)
                    if isinstance(value, dict):
                        return validate_result(value).model_dump(mode="json")
                except (ValueError, ResultValidationError):
                    continue
        raise AdapterFailure("provider did not return a valid structured result")


class KiroJSONLinesCodec(JSONLinesCodec):
    provider = "kiro"


class CodexJSONLinesCodec(JSONLinesCodec):
    provider = "codex"
