"""edbo web platform — FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import (
    projects, space, optimization, experiments, analytics, rules, descriptors,
)

app = FastAPI(title="edbo Web Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(projects.router)
app.include_router(space.router)
app.include_router(optimization.router)
app.include_router(experiments.router)
app.include_router(analytics.router)
app.include_router(rules.router)
app.include_router(descriptors.router)
