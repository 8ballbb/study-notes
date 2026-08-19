from study_notes.agent.context import EngineContext


def test_engine_context_holds_handles():
    ctx = EngineContext(config="C", index="I", writer="W")  # type: ignore[arg-type]
    assert ctx.config == "C" and ctx.index == "I" and ctx.writer == "W"
