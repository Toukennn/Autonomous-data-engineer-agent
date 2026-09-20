import json
from pathlib import Path

from fastapi import APIRouter, HTTPException


recorded_demo_router = APIRouter(
    prefix="/demo/recorded",
    tags=["recorded-demo"],
)

_RECORDED_ROOT = (
    Path(__file__).resolve().parent
    / "recorded_runs"
)

_ALLOWED_RUNS = {
    "revenue-by-country",
    "gold-preview",
    "missing-values",
    "blocked-pg-catalog",
}


def _load_json(filename: str) -> dict:
    path = (
        _RECORDED_ROOT
        / filename
    ).resolve()

    try:
        path.relative_to(
            _RECORDED_ROOT.resolve()
        )
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Recorded run not found.",
        ) from None

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(file)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        raise HTTPException(
            status_code=404,
            detail="Recorded run not found.",
        ) from None

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=404,
            detail="Recorded run not found.",
        )

    return payload


@recorded_demo_router.get("")
def recorded_runs() -> dict:
    return _load_json(
        "index.json"
    )


@recorded_demo_router.get("/{slug}")
def recorded_run(slug: str) -> dict:
    if slug not in _ALLOWED_RUNS:
        raise HTTPException(
            status_code=404,
            detail="Recorded run not found.",
        )

    return _load_json(
        f"{slug}.json"
    )
