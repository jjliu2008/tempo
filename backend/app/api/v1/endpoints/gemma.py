"""App-facing Gemma calls; credentials and Google SDK remain server-side."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_agent_orchestrator, get_gemma_service
from app.schemas.gemma import GemmaRequest, GemmaResponse, MultiAgentRequest, MultiAgentResponse
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.gemma import GemmaService

router = APIRouter()
GemmaDependency = Annotated[GemmaService, Depends(get_gemma_service)]
AgentOrchestratorDependency = Annotated[
    AgentOrchestrator, Depends(get_agent_orchestrator)
]


@router.post("/generate", response_model=GemmaResponse)
async def generate(body: GemmaRequest, service: GemmaDependency) -> GemmaResponse:
    return await service.generate(body)


@router.post("/agents", response_model=MultiAgentResponse)
async def run_agents(
    body: MultiAgentRequest, orchestrator: AgentOrchestratorDependency
) -> MultiAgentResponse:
    return await orchestrator.run_agents(body)
