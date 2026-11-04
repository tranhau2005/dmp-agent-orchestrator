from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="DMP Agent Orchestrator")


app = create_app()
