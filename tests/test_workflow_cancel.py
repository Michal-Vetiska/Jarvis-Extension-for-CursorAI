import time

from jarvis.orchestrator import Step, WorkflowContext, WorkflowEngine


def test_workflow_cancel_midway():
    engine = WorkflowEngine()
    events = []

    def slow(ctx: WorkflowContext):
        for _ in range(50):
            if ctx.cancelled or engine._cancel.is_set():
                raise RuntimeError("cancelled")
            time.sleep(0.02)
        return {"ok": True}

    def never(ctx: WorkflowContext):
        return {"ok": True}

    import threading

    result_box = {}

    def runner():
        result_box["r"] = engine.run(
            "t",
            "proj",
            "do",
            [
                Step("SLOW", slow, timeout=5),
                Step("NEVER", never, timeout=1),
            ],
        )

    t = threading.Thread(target=runner)
    t.start()
    time.sleep(0.05)
    engine.cancel()
    t.join(timeout=3)
    assert result_box["r"]["status"] in {"cancelled", "failed"}
