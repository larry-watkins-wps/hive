"""POST /sensory/text/in — translator output endpoint.

The single v4 endpoint. Future audio/visual endpoints sit beside this
under the `/sensory/*` prefix. The publisher dependency is provided
via FastAPI's dependency-injection so component tests + unit tests
can swap the real publisher for a stub.

Spec §4.4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from observatory.config import Settings
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from observatory.sensory.publisher import SensoryPublisher
from shared.message_envelope import Envelope

_NO_STORE = {"Cache-Control": "no-store"}


# Dependency providers — overridden in tests via `app.dependency_overrides`.
def get_publisher(request: Request) -> SensoryPublisher:
    return request.app.state.sensory_publisher


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


# Module-level Depends() singletons sidestep ruff B008 ("don't call functions
# in default args") while preserving FastAPI's dependency-injection idiom.
_PUBLISHER_DEP = Depends(get_publisher)
_SETTINGS_DEP = Depends(get_settings)


class TextInRequest(BaseModel):
    text: str = Field(min_length=1)
    speaker: str | None = None

    @field_validator("text")
    @classmethod
    def _trim_and_check(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("text is empty after trim")
        return trimmed


class TextInResponse(BaseModel):
    id: str
    timestamp: str


def build_sensory_router() -> APIRouter:
    router = APIRouter()

    @router.post("/sensory/text/in", status_code=202, response_model=TextInResponse)
    async def text_in(
        body: TextInRequest,
        publisher: SensoryPublisher = _PUBLISHER_DEP,
        settings: Settings = _SETTINGS_DEP,
    ) -> JSONResponse:
        # Late max-length check uses runtime Settings, not an import-time literal.
        if len(body.text) > settings.chat_text_max_length:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "text"],
                        "msg": (
                            f"text exceeds chat_text_max_length="
                            f"{settings.chat_text_max_length}"
                        ),
                        "type": "value_error",
                    }
                ],
            )

        speaker = (
            body.speaker if body.speaker is not None else settings.chat_default_speaker
        )
        envelope = Envelope.new(
            # See spec §3.2: shared/message_envelope.py constrains source_region
            # to ^[a-z][a-z0-9_]{2,30}$, so the dotted "observatory.sensory" form
            # the early v4 draft used was rejected by Hive's region-side schema
            # validator. observatory_sensory keeps the prefix-based filtering hint.
            source_region="observatory_sensory",
            topic="hive/external/perception",
            content_type="application/json",
            data={
                "text": body.text,
                "speaker": speaker,
                "channel": "observatory.chat",
                "source_modality": "text",
            },
        )
        try:
            await publisher.publish(envelope, qos=settings.chat_publish_qos)
        except ForbiddenTopicError as e:
            # Programming error: route always builds an allowlisted topic.
            return JSONResponse(
                status_code=500,
                content={"error": "forbidden_topic", "message": str(e)},
                headers=_NO_STORE,
            )
        except PublishFailedError as e:
            return JSONResponse(
                status_code=502,
                content={"error": "publish_failed", "message": str(e)},
                headers=_NO_STORE,
            )

        return JSONResponse(
            status_code=202,
            content={"id": envelope.id, "timestamp": envelope.timestamp},
            headers=_NO_STORE,
        )

    return router
