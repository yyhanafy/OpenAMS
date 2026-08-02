from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

class DependencyExecutionError(RuntimeError):
    pass

@dataclass(frozen=True)
class ExecutionRecord:
    rule_id: str
    operation: str
    outputs: tuple[str, ...]

TechnologyCallback = Callable[[dict[str, Any], Mapping[str, Any]], Mapping[str, Any]]

class ContinuousDependencyExecutor:
    def __init__(self, *, technology_callbacks: Mapping[str, TechnologyCallback] | None = None):
        self.technology_callbacks = dict(technology_callbacks or {})

    @staticmethod
    def _require(state: Mapping[str, Any], names: Iterable[str]) -> None:
        missing = [name for name in names if name not in state]
        if missing:
            raise DependencyExecutionError("missing dependencies: " + ", ".join(missing))

    def execute(self, *, initial_state: Mapping[str, Any], rules: Iterable[Mapping[str, Any]]):
        state = dict(initial_state)
        records = []
        for index, rule in enumerate(rules):
            rule_id = str(rule.get("id", f"rule_{index:04d}"))
            op = str(rule["operation"])
            outputs: tuple[str, ...]

            if op == "assign":
                out = str(rule["output"])
                state[out] = rule["value"]
                outputs = (out,)
            elif op == "copy":
                src, out = str(rule["source"]), str(rule["output"])
                self._require(state, [src])
                state[out] = state[src]
                outputs = (out,)
            elif op == "divide":
                src, out = str(rule["numerator"]), str(rule["output"])
                self._require(state, [src])
                state[out] = state[src] / float(rule["denominator"])
                outputs = (out,)
            elif op == "multiply":
                src, out = str(rule["source"]), str(rule["output"])
                self._require(state, [src])
                state[out] = state[src] * float(rule["factor"])
                outputs = (out,)
            elif op == "subtract":
                left, right, out = str(rule["left"]), str(rule["right"]), str(rule["output"])
                self._require(state, [left, right])
                state[out] = state[left] - state[right]
                outputs = (out,)
            elif op == "technology_call":
                name = str(rule["callback"])
                cb = self.technology_callbacks.get(name)
                if cb is None:
                    raise DependencyExecutionError(f"technology callback not registered: {name}")
                self._require(state, [str(x) for x in rule.get("requires", [])])
                result = dict(cb(state, rule))
                expected = tuple(str(x) for x in rule.get("outputs", []))
                missing = [x for x in expected if x not in result]
                if missing:
                    raise DependencyExecutionError(f"{name} did not return: " + ", ".join(missing))
                state.update(result)
                outputs = expected or tuple(result)
            elif op == "check_close":
                left, right = str(rule["left"]), str(rule["right"])
                self._require(state, [left, right])
                error = abs(float(state[left]) - float(state[right]))
                tol = float(rule["tolerance"])
                if error > tol:
                    raise DependencyExecutionError(f"{rule_id} failed: error={error} > {tol}")
                outputs = ()
            else:
                raise DependencyExecutionError(f"unsupported operation: {op}")

            records.append(ExecutionRecord(rule_id, op, outputs))
        return state, records
