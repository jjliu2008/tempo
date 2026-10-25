"""Request-local multi-agent scheduling over the Gemma generation service."""

import asyncio

from pydantic import JsonValue

from app.schemas.gemma import (
    AgentRequest,
    AgentResponse,
    GemmaRequest,
    MultiAgentRequest,
    MultiAgentResponse,
)
from app.services.gemma import GemmaService


class AgentOrchestrator:
    def __init__(self, gemma: GemmaService) -> None:
        self._gemma = gemma

    async def run_agents(self, request: MultiAgentRequest) -> MultiAgentResponse:
        tasks: dict[str, asyncio.Task[AgentResponse]] = {}

        async def run(agent: AgentRequest) -> AgentResponse:
            dependencies = {name: await tasks[name] for name in agent.depends_on}
            context: dict[str, JsonValue] = {}
            if request.context is not None:
                context["shared_context"] = request.context
            if agent.context is not None:
                context["agent_context"] = agent.context
            if dependencies:
                context["agent_results"] = {
                    name: {"text": result.text, "model": result.model}
                    for name, result in dependencies.items()
                }
            system_prompt = (
                "\n\n".join(
                    prompt for prompt in (request.system_prompt, agent.system_prompt) if prompt
                )
                or None
            )
            # Validate the composed context just like a direct call, without mutating the agent.
            composed = GemmaRequest(
                prompt=agent.prompt,
                system_prompt=system_prompt,
                context=context or None,
                history=agent.history,
                temperature=agent.temperature,
                max_output_tokens=agent.max_output_tokens,
            )
            result = await self._gemma.generate(composed)
            return AgentResponse(id=agent.id, **result.model_dump())

        # All tasks are registered before the first await, including forward dependencies.
        for agent in request.agents:
            tasks[agent.id] = asyncio.create_task(run(agent))
        try:
            results = await asyncio.gather(*tasks.values())
        except BaseException:
            # gather alone leaves siblings running (and spending quota) after a failure.
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise
        return MultiAgentResponse(results=results)
