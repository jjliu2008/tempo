"""Text/JSON context, conversation, and multi-agent contracts for Gemma."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

NonEmptyText = Annotated[str, Field(min_length=1)]
AgentId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
Context = str | dict[str, JsonValue] | list[JsonValue]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model"]
    content: NonEmptyText
    context: Context | None = None

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value

    @model_validator(mode="after")
    def context_belongs_to_user(self) -> Self:
        if self.role != "user" and self.context is not None:
            raise ValueError("Only user turns can contain application context")
        return self


class GemmaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: NonEmptyText
    system_prompt: str | None = None
    context: Context | None = None
    history: list[Message] = Field(default_factory=list)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32768, strict=True)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must not be blank")
        return value

    @field_validator("history")
    @classmethod
    def validate_turns(cls, history: list[Message]) -> list[Message]:
        for index, message in enumerate(history):
            expected = "user" if index % 2 == 0 else "model"
            if message.role != expected:
                raise ValueError("History must alternate user/model turns, starting with user")
        if len(history) % 2:
            raise ValueError(
                "History must end with a model turn; supply the new user turn as prompt"
            )
        return history


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class GemmaResponse(BaseModel):
    text: str
    model: str
    history: list[Message]
    finish_reason: str | None = None
    usage: TokenUsage


class AgentRequest(GemmaRequest):
    id: AgentId
    depends_on: list[AgentId] = Field(default_factory=list)


class MultiAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentRequest] = Field(min_length=1, max_length=16)
    system_prompt: str | None = None
    context: Context | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        ids = {agent.id for agent in self.agents}
        if len(ids) != len(self.agents):
            raise ValueError("Agent ids must be unique")
        for agent in self.agents:
            if len(set(agent.depends_on)) != len(agent.depends_on):
                raise ValueError(f"Agent {agent.id!r} has duplicate dependencies")
            if unknown := set(agent.depends_on) - ids:
                raise ValueError(f"Agent {agent.id!r} has unknown dependencies: {sorted(unknown)}")
        completed: set[str] = set()
        while len(completed) < len(ids):
            ready = {
                agent.id
                for agent in self.agents
                if agent.id not in completed and set(agent.depends_on) <= completed
            }
            if not ready:
                raise ValueError("Agent dependencies must not contain cycles")
            completed.update(ready)
        return self


class AgentResponse(GemmaResponse):
    id: str


class MultiAgentResponse(BaseModel):
    results: list[AgentResponse]
