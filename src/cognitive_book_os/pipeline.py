"""Ingestion Pipeline Strategies.

Decouples the 'reading' of chapters from the 'processing' logic,
allowing for different strategies like skipping irrelevant chapters.
"""

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime
from rich.console import Console

from .brain import Brain
from .llm import LLMClient
from .models import ObjectiveSynthesis, ChapterState, ChapterStatus
from .agent import run_extraction_agent
# from .ingest import synthesize_objective  # Circular import risk

console = Console()

class IngestionStrategy(ABC):
    """Abstract base class for ingestion strategies."""
    
    @abstractmethod
    def process_chapter(
        self,
        chapter_content: str,
        chapter_title: str,
        chapter_num: int,
        brain: Brain,
        client: LLMClient,
        objective: Optional[str] = None,
        fast_mode: bool = False
    ) -> ChapterState:
        """
        Process a single chapter.
        
        Returns:
            ChapterState with status and reason.
        """
        pass

class StandardStrategy(IngestionStrategy):
    """
    The standard 2-pass approach:
    1. Extract & Organize (Agent)
    2. Synthesize Objective (Analyst)
    """
    
    def process_chapter(
        self,
        chapter_content: str,
        chapter_title: str,
        chapter_num: int,
        brain: Brain,
        client: LLMClient,
        objective: Optional[str] = None,
        fast_mode: bool = False
    ) -> ChapterState:
        # Pass 1: Extract and organize using agent
        console.print("  [dim]Pass 1: Extracting information (agent)...[/dim]")
        agent_result = run_extraction_agent(
            chapter_content=chapter_content,
            chapter_title=chapter_title,
            chapter_num=chapter_num,
            brain=brain,
            client=client
        )
        console.print(f"  [dim]Created: {agent_result['files_created']}, Updated: {agent_result['files_updated']}, Iterations: {agent_result['iterations']}[/dim]")
        
        # Pass 2: Synthesize toward objective (skip in fast mode OR if no objective)
        if not fast_mode and objective:
            console.print("  [dim]Pass 2: Synthesizing toward objective...[/dim]")
            from .ingest import synthesize_objective
            
            synth_result = synthesize_objective(
                chapter_content=chapter_content,
                chapter_title=chapter_title,
                chapter_num=chapter_num,
                brain=brain,
                client=client
            )
            console.print(f"  [dim]Confidence: {synth_result.confidence.value}[/dim]")
            
        return ChapterState(
            chapter_num=chapter_num,
            status=ChapterStatus.EXTRACTED,
            timestamp=datetime.now().isoformat()
        )

class TriageStrategy(IngestionStrategy):
    """
    Triage approach:
    1. Check if chapter is relevant using a cheap/fast check.
    2. If YES -> Delegate to StandardStrategy.
    3. If NO -> Skip.
    """
    
    def __init__(self):
        self.standard_strategy = StandardStrategy()
        
    def process_chapter(
        self,
        chapter_content: str,
        chapter_title: str,
        chapter_num: int,
        brain: Brain,
        client: LLMClient,
        objective: Optional[str] = None,
        fast_mode: bool = False
    ) -> ChapterState:
        if not objective:
            # If no objective, we can't triage. Fallback to standard.
            return self.standard_strategy.process_chapter(
                chapter_content, chapter_title, chapter_num, brain, client, objective, fast_mode
            )
            
        # Triage Step
        console.print("  [dim]Triaging chapter relevance...[/dim]")
        
        from pydantic import BaseModel, Field
        
        class TriageDecision(BaseModel):
            is_relevant: bool = Field(..., description="Whether this chapter contains information relevant to the objective.")
            reasoning: str = Field(..., description="Brief reason for the decision.")
            
        system_prompt = "You are a content filter. Decide if the text is relevant to the user's objective."
        user_prompt = f"""## User Objective
{objective}

## Chapter Text (Title: {chapter_title})
{chapter_content[:10000]} ... (truncated)

---

Is this chapter relevant to the objective? Reply YES if it contains ANY potentially useful information. Reply NO only if it is completely irrelevant.
"""
        try:
            decision = client.generate(
                response_model=TriageDecision,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0
            )
        except Exception as e:
            console.print(f"[yellow]Triage failed, failing open (processing): {e}[/yellow]")
            decision = TriageDecision(is_relevant=True, reasoning="Error in triage")

        if decision.is_relevant:
            console.print(f"  [green]Relevant:[/green] {decision.reasoning}")
            # Delegate to Standard Strategy
            return self.standard_strategy.process_chapter(
                chapter_content, chapter_title, chapter_num, brain, client, objective, fast_mode
            )
        else:
            console.print(f"  [yellow]Skipped:[/yellow] {decision.reasoning}")
            return ChapterState(
                chapter_num=chapter_num,
                status=ChapterStatus.SKIPPED,
                reason=decision.reasoning,
                timestamp=datetime.now().isoformat()
            )

def get_strategy(name: str) -> IngestionStrategy:
    if name.lower() == "triage":
        return TriageStrategy()
    return StandardStrategy()
