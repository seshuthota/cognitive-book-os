"""Enrichment Manager: Handles the 'learning new things' loop."""

from pathlib import Path
from rich.console import Console

from .brain import Brain
from .models import ChapterStatus
from .ingest import process_document
from .llm import LLMClient
from .config import BRAIN_MODEL

console = Console()


class EnrichmentManager:
    """
    Manages the enrichment process for an existing brain.
    Identifies skipped chapters and re-scans them with a new objective.
    """
    
    def __init__(self, brain_name: str, brains_dir: str = "brains"):
        self.brain_name = brain_name
        self.brains_dir = brains_dir
        self.brain = Brain(name=brain_name, base_path=brains_dir)
        
    def evaluate_gap(self, query: str, provider: str = "anthropic", model: str | None = None) -> tuple[bool, list[int]]:
        """
        Check if skipped chapters might contain the answer to the query.
        
        Uses a hybrid approach:
        1. Literal String Match (Safety Net) - $0 cost, catches obvious matches
        2. LLM Gap Detector (Fallback) - For semantic/contextual matches
        
        Args:
            query: The user's question.
            provider: LLM provider.
            model: Model to use.
            
        Returns:
            (should_enrich, list_of_chapters_to_process)
        """
        if not self.brain.exists():
            return False, []
            
        log = self.brain.get_processing_log()
        
        # 1. Identify skipped chapters
        skipped_map = {}  # {num: reason}
        for chapter_str, state in log.chapter_map.items():
            if state.status == ChapterStatus.SKIPPED:
                skipped_map[int(chapter_str)] = state.reason or "No reason provided."
                
        if not skipped_map:
            return False, []
        
        # ============================================
        # STEP 0: Literal String Match (Safety Net)
        # ============================================
        # Extract potential proper nouns / key terms from query
        # Simple approach: words that are capitalized or look like names
        import re
        
        # Extract quoted terms, capitalized words, and multi-word proper nouns
        query_terms = set()
        
        # Get words that start with capital letters (potential proper nouns)
        words = query.split()
        for word in words:
            # Clean punctuation
            clean_word = re.sub(r'[^\w]', '', word)
            if clean_word and len(clean_word) > 2:
                # Add both original case and lowercase for matching
                query_terms.add(clean_word.lower())
        
        # Also extract quoted strings if any
        quoted = re.findall(r'"([^"]+)"', query)
        for q in quoted:
            query_terms.add(q.lower())
        
        # Check for literal matches in skip reasons
        matched_chapters = []
        all_reasons_text = ""
        for chapter_num, reason in skipped_map.items():
            reason_lower = reason.lower()
            all_reasons_text += reason_lower + " "
            
            for term in query_terms:
                if term in reason_lower:
                    console.print(f"[dim]Safety Net: Literal match '{term}' found in Chapter {chapter_num} skip reason[/dim]")
                    if chapter_num not in matched_chapters:
                        matched_chapters.append(chapter_num)
        
        if matched_chapters:
            console.print(f"[bold green]Gap Detector (Literal Match):[/bold green] Found matches in {len(matched_chapters)} chapters")
            return True, list(skipped_map.keys())  # Enrich all skipped chapters
        
        # ============================================
        # STEP 1: LLM Gap Detector (Semantic Fallback)
        # ============================================
        console.print("[dim]No literal matches. Checking semantic relevance via LLM...[/dim]")
        
        system_prompt = """You are a Gap Detector for a Cognitive Book. Your job is to check if a question can be answered by reviewing chapters that were previously skipped.

IMPORTANT: A match found within a skip reason OVERRIDES the fact that the chapter was skipped for a different topic. Focus on finding ANY relevant entities, names, or concepts."""

        user_prompt = f"""QUESTION: "{query}"

SKIP REASONS:
"""
        for num, reason in sorted(skipped_map.items()):
            user_prompt += f"- Chapter {num}: {reason}\n"
            
        user_prompt += """
INSTRUCTIONS:
1. Identify the key entities, names, or specific terms in the QUESTION.
2. For each Chapter Reason provided, check if any of those key terms appear (even as minor mentions).
3. If a match is found, identify which chapter it is in.
4. Conclude with 'YES' if a match is found, or 'NO' if absolutely no match is found.

Provide your response in this format:
ANALYSIS: [One sentence identifying matches or lack thereof]
RESULT: [YES or NO]
"""

        # Call LLM
        client = LLMClient(provider=provider, model=model or BRAIN_MODEL)
        response = client.generate_text(system_prompt, user_prompt, max_tokens=200).strip()
        
        # Parse response - look for RESULT line
        should_enrich = False
        if "RESULT:" in response.upper():
            result_line = response.upper().split("RESULT:")[-1].strip()
            should_enrich = "YES" in result_line
        else:
            # Fallback: look for YES anywhere
            should_enrich = "YES" in response.upper()
        
        # Log the analysis for debugging
        if "ANALYSIS:" in response.upper():
            analysis = response.split("ANALYSIS:")[-1].split("RESULT:")[0].strip() if "RESULT:" in response.upper() else response
            console.print(f"[dim]Gap Analysis: {analysis[:200]}[/dim]")
        
        target_chapters = list(skipped_map.keys()) if should_enrich else []
        
        return should_enrich, target_chapters

    def enrich(self, new_objective: str, provider: str = "anthropic", model: str | None = None) -> None:
        """
        Perform the enrichment (delta scan).
        
        Args:
            new_objective: The new question/topic to look for.
            provider: LLM provider
            model: Optional model override
        """
        if not self.brain.exists():
            console.print(f"[bold red]Error:[/bold red] Brain '{self.brain_name}' not found.")
            return
            
        log = self.brain.get_processing_log()
        
        # Calculate Delta: Find skipped chapters
        skipped_chapters = []
        for chapter_str, state in log.chapter_map.items():
            if state.status == ChapterStatus.SKIPPED:
                skipped_chapters.append(int(chapter_str))
        
        if not skipped_chapters:
            console.print("[yellow]No skipped chapters found to enrich.[/yellow]")
            console.print("The brain might be fully extracted already, or created with a legacy version.")
            return
            
        console.print(f"[bold cyan]Enrichment Protocol Initiated[/bold cyan]")
        console.print(f"Target: {len(skipped_chapters)} previously skipped chapters")
        console.print(f"New Objective: {new_objective}")
        
        # Validate Book Path
        book_path = Path(log.book_path)
        if not book_path.exists():
            console.print(f"[bold red]Error:[/bold red] Original source file not found at: {book_path}")
            return
            
        # Run Pipeline (Targeted)
        # We enforce 'triage' strategy to save costs on the new pass.
        # If the user wants to force-read everything, they should use 'ingest --strategy standard'
        # with specific flags, but 'enrich' implies efficiency.
        process_document(
            document_path=book_path,
            brain_name=self.brain_name,
            objective=new_objective,
            provider=provider,
            model=model,
            brains_dir=self.brains_dir,
            strategy_name="triage",
            allowed_chapters=skipped_chapters
        )
        
        # Update Secondary Objectives
        # Reload log because process_document updated the chapter_map
        log = self.brain.get_processing_log()
        
        if new_objective not in log.secondary_objectives:
            log.secondary_objectives.append(new_objective)
            self.brain.update_processing_log(secondary_objectives=log.secondary_objectives)
            
        console.print(f"[bold green]Enrichment Complete.[/bold green]")
        console.print(f"Updated metadata: meta/processing_log.json")


