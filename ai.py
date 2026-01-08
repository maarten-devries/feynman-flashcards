"""AI Service Module

Provides functions for:
- Rephrasing flashcard questions
- Evaluating user answers with Socratic follow-ups
- Speech-to-text transcription
- Text-to-speech synthesis

Supports both OpenAI and Anthropic (Claude) APIs.
"""

import json
import re
import httpx
from openai import OpenAI
import anthropic
from typing import Optional, Union


def get_openai_client(api_key: str) -> OpenAI:
    """Create OpenAI client with user's API key."""
    return OpenAI(api_key=api_key)


def get_anthropic_client(api_key: str) -> anthropic.Anthropic:
    """Create Anthropic client with user's API key."""
    return anthropic.Anthropic(api_key=api_key)


def get_client(api_key: str) -> OpenAI:
    """Create OpenAI client with user's API key (legacy support)."""
    return OpenAI(api_key=api_key)


async def validate_openai_key(api_key: str) -> tuple[bool, str]:
    """
    Validate an OpenAI API key by listing models.
    
    Returns:
        (success, message) tuple
    """
    try:
        client = get_openai_client(api_key)
        # Simple validation - list models
        client.models.list()
        return True, "Connected to OpenAI"
    except Exception as e:
        error_msg = str(e)
        if "invalid_api_key" in error_msg.lower() or "401" in error_msg:
            return False, "Invalid API key"
        return False, f"Connection error: {error_msg[:100]}"


async def validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    """
    Validate an Anthropic API key by making a simple request.
    
    Returns:
        (success, message) tuple
    """
    try:
        client = get_anthropic_client(api_key)
        # Simple validation - count tokens (lightweight request)
        client.messages.count_tokens(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "test"}],
        )
        return True, "Connected to Anthropic"
    except anthropic.AuthenticationError:
        return False, "Invalid API key"
    except Exception as e:
        error_msg = str(e)
        return False, f"Connection error: {error_msg[:100]}"


async def validate_api_key(api_key: str) -> tuple[bool, str]:
    """Legacy function - validates OpenAI key."""
    return await validate_openai_key(api_key)


def parse_card_content(content: str) -> tuple[str, str, Optional[str]]:
    """
    Parse Mochi card content into question, answer, and source.
    
    Mochi cards typically use --- to separate front/back,
    or use template fields like << Front >> and << Back >>.
    Source field can be specified as "Source: <url>" or in a template field.
    
    Returns:
        (question, answer, source_url) tuple
    """
    source_url = None
    
    # Extract Source field if present (various formats)
    # Format 1: "Source: <url>" on its own line
    source_match = re.search(r'^Source:\s*(https?://\S+)', content, re.MULTILINE | re.IGNORECASE)
    if source_match:
        source_url = source_match.group(1).strip()
        # Remove the source line from content for cleaner parsing
        content = re.sub(r'^Source:\s*https?://\S+\s*\n?', '', content, flags=re.MULTILINE | re.IGNORECASE)
    
    # Format 2: Template field << Source >>
    template_source_match = re.search(r'<<\s*Source\s*>>\s*\n?(https?://\S+)', content, re.IGNORECASE)
    if template_source_match and not source_url:
        source_url = template_source_match.group(1).strip()
    
    # Handle --- separator (most common)
    if "---" in content:
        parts = content.split("---", 1)
        question = parts[0].strip()
        answer = parts[1].strip() if len(parts) > 1 else ""
        # Clean up markdown headers
        question = question.lstrip("#").strip()
        return question, answer, source_url
    
    # Handle << Field >> template syntax
    if "<<" in content and ">>" in content:
        # This is a template card - just use the whole content
        return content, "", source_url
    
    # Fallback: treat first line as question, rest as answer
    lines = content.strip().split("\n", 1)
    question = lines[0].lstrip("#").strip()
    answer = lines[1].strip() if len(lines) > 1 else ""
    return question, answer, source_url


async def fetch_source_content(url: str, max_length: int = 15000) -> Optional[str]:
    """
    Fetch and extract main content from a source URL.
    
    Args:
        url: The URL to fetch
        max_length: Maximum characters to return (to fit in context)
        
    Returns:
        Extracted text content or None if fetch fails
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            response.raise_for_status()
            html = response.text
            
            # Simple extraction: remove scripts, styles, and HTML tags
            # Remove script and style elements
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
            
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', ' ', html)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Decode HTML entities
            import html as html_module
            text = html_module.unescape(text)
            
            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "... [truncated]"
            
            return text if text else None
            
    except Exception as e:
        print(f"Error fetching source: {e}")
        return None


def rephrase_question(
    api_key: str,
    question: str,
    answer: str,
    context: str = "",
    provider: str = "openai",
) -> str:
    """
    Generate a rephrased version of a flashcard question.
    
    The rephrasing preserves the core concept being tested but uses
    different wording, context, or framing to prevent pattern memorization.
    
    Args:
        api_key: API key for the selected provider
        question: Original question from the card
        answer: Expected answer (to preserve difficulty)
        context: Optional additional context about the topic
        provider: "openai" or "anthropic"
        
    Returns:
        Rephrased question string
    """
    system_prompt = """You are an expert educator helping students deeply understand concepts.

Your task is to rephrase flashcard questions to test the SAME concept but with different wording.
This prevents students from memorizing card layouts instead of actual knowledge.

Guidelines:
- Preserve the core concept and difficulty level
- Use different wording, analogies, or contexts
- The same answer should still be correct
- Be concise - this is a flashcard, not an essay question
- Do NOT include the answer in your rephrased question
- Vary your approach: sometimes ask for definitions, sometimes for examples, sometimes for comparisons"""

    user_prompt = f"""Rephrase this flashcard question:

Original Question: {question}

Expected Answer: {answer}

{f"Context: {context}" if context else ""}

Provide ONLY the rephrased question, nothing else."""

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
    else:
        client = get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_completion_tokens=300,
        )
        return response.choices[0].message.content.strip()


def evaluate_answer(
    api_key: str,
    question: str,
    expected_answer: str,
    user_answer: str,
    conversation_history: Optional[list[dict]] = None,
    provider: str = "openai",
    source_content: Optional[str] = None,
) -> dict:
    """
    Evaluate a user's answer and provide Socratic feedback.
    
    Args:
        api_key: API key for the selected provider
        question: The question that was asked
        expected_answer: The correct/expected answer
        user_answer: What the user provided
        conversation_history: Previous exchanges for follow-up context
        provider: "openai" or "anthropic"
        source_content: Optional content from the source URL for additional context
        
    Returns:
        Dict with:
        - is_correct: bool - whether understanding is demonstrated
        - score: float 0-1 - confidence in correctness
        - feedback: str - explanation of what's right/wrong
        - follow_up: str|None - follow-up question if needed
    """
    source_context = ""
    if source_content:
        source_context = f"""

You also have access to the original source material this flashcard was created from.
Use this to provide deeper, more informed feedback and ask more insightful follow-up questions.

SOURCE CONTENT:
{source_content[:10000]}
"""
    
    system_prompt = f"""You are a Socratic tutor evaluating student understanding.

Your role is to:
1. Assess if the student's answer demonstrates understanding of the core concept
2. Provide constructive feedback
3. If understanding is incomplete, ask a follow-up question to probe deeper
{source_context}
Be encouraging but honest. Focus on conceptual understanding, not exact wording.
A partially correct answer should get a follow-up question to clarify gaps.

Respond in JSON format:
{{
    "is_correct": true/false,
    "score": 0.0-1.0,
    "feedback": "Your explanation of what's right/wrong",
    "follow_up": "A follow-up question if needed, or null if understanding is complete"
}}"""

    # Build conversation history context
    history_text = ""
    if conversation_history:
        for entry in conversation_history:
            history_text += f"\nPrevious evaluation: {json.dumps(entry['evaluation'])}"
            history_text += f"\nStudent responded: {entry['user_answer']}\n"

    user_prompt = f"""Question asked: {question}

Expected answer: {expected_answer}

Student's answer: {user_answer}
{history_text}
Evaluate this answer and respond in JSON format."""

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = json.loads(response.content[0].text)
    else:
        client = get_openai_client(api_key)
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_prompt})
        
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=500,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
    
    # Ensure all expected fields exist
    return {
        "is_correct": result.get("is_correct", False),
        "score": result.get("score", 0.0),
        "feedback": result.get("feedback", "Unable to evaluate."),
        "follow_up": result.get("follow_up"),
    }


def transcribe_audio(api_key: str, audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """
    Transcribe audio to text using OpenAI's speech-to-text.
    
    Args:
        api_key: OpenAI API key
        audio_bytes: Raw audio bytes
        filename: Filename hint for format detection
        
    Returns:
        Transcribed text
    """
    import io
    client = get_client(api_key)
    
    # Streamlit's audio_input returns wav format
    # Create a proper file-like object with the audio data
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    
    response = client.audio.transcriptions.create(
        model="whisper-1",  # whisper-1 is more reliable for various formats
        file=audio_file,
        response_format="text",
    )
    
    return response.strip()


def text_to_speech(api_key: str, text: str, voice: str = "coral") -> bytes:
    """
    Convert text to speech using OpenAI's TTS.
    
    Args:
        api_key: OpenAI API key
        text: Text to speak
        voice: Voice to use (alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer)
        
    Returns:
        Audio bytes (MP3 format)
    """
    client = get_client(api_key)
    
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        instructions="Speak clearly and at a moderate pace, like a friendly tutor.",
        response_format="mp3",
    )
    
    return response.content


def chat_followup(
    api_key: str,
    conversation_history: list[dict],
    original_question: str,
    original_answer: str,
    user_message: str,
    provider: str = "openai",
    source_content: Optional[str] = None,
) -> str:
    """
    Continue a conversation about the flashcard topic.
    
    Args:
        api_key: API key for the selected provider
        conversation_history: Previous messages in the conversation
        original_question: The card's question
        original_answer: The card's answer
        user_message: The user's follow-up question
        provider: "openai" or "anthropic"
        source_content: Optional content from the source URL for additional context
        
    Returns:
        AI response as string
    """
    source_context = ""
    if source_content:
        source_context = f"""

You also have access to the original source material this flashcard was created from:

SOURCE CONTENT:
{source_content[:10000]}

Use this source to provide more detailed, accurate answers and to point out additional
relevant information from the original material that the user might find helpful."""
    
    system_prompt = f"""You are a Socratic tutor helping someone deeply understand a topic.

Context - The flashcard being studied:
Question: {original_question}
Answer: {original_answer}
{source_context}
Help the user understand this topic better. Answer their questions, provide clarifications, 
give examples, and help them build intuition. Be concise but thorough.

If they ask to modify or improve the card, suggest specific improvements to the question or answer.
If they want to create a new card, help them formulate a clear question and answer."""

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        messages = []
        for msg in conversation_history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_message})
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    else:
        client = get_openai_client(api_key)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_message})
        
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=messages,
            temperature=0.7,
            max_completion_tokens=1000,
        )
        return response.choices[0].message.content


def suggest_card_modification(
    api_key: str,
    original_question: str,
    original_answer: str,
    conversation_history: list[dict],
    provider: str = "openai",
) -> dict:
    """
    Suggest an improved version of the card based on the conversation.
    
    Args:
        provider: "openai" or "anthropic"
    
    Returns:
        Dict with 'question' and 'answer' keys
    """
    # Format conversation for context
    convo_text = "\n".join([
        f"{'User' if m['role'] == 'user' else 'Tutor'}: {m['content']}"
        for m in conversation_history[-10:]
    ])
    
    system_prompt = """Based on the conversation, suggest an improved version of this flashcard.
Consider:
- Clarity and precision of the question
- Completeness and accuracy of the answer
- Any misconceptions or gaps that came up in discussion

Return a JSON object with 'question' and 'answer' keys.
Only suggest changes if they genuinely improve the card."""

    user_prompt = f"""Original card:
Question: {original_question}
Answer: {original_answer}

Conversation:
{convo_text}

Suggest an improved version (or return the original if no changes needed):"""

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return json.loads(response.content[0].text)
    else:
        client = get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


def suggest_new_card(
    api_key: str,
    original_question: str,
    original_answer: str,
    conversation_history: list[dict],
    user_request: str = "",
    provider: str = "openai",
) -> dict:
    """
    Suggest a new card based on the conversation.
    
    Args:
        provider: "openai" or "anthropic"
    
    Returns:
        Dict with 'question' and 'answer' keys
    """
    # Format conversation for context
    convo_text = "\n".join([
        f"{'User' if m['role'] == 'user' else 'Tutor'}: {m['content']}"
        for m in conversation_history[-10:]
    ])
    
    system_prompt = """Based on the conversation, create a new flashcard that captures
an important concept, clarification, or insight that came up.

The new card should:
- Be self-contained and testable
- Cover a specific concept or fact
- Have a clear question and concise answer

Return a JSON object with 'question' and 'answer' keys."""

    user_prompt = f"""Original card being studied:
Question: {original_question}
Answer: {original_answer}

Conversation:
{convo_text}
"""
    if user_request:
        user_prompt += f"\nUser's request for the new card: {user_request}"
    
    user_prompt += "\n\nCreate a new flashcard:"

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return json.loads(response.content[0].text)
    else:
        client = get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


def generate_expansion_cards(
    api_key: str,
    question: str,
    answer: str,
    concept_to_expand: str = "",
    num_cards: int = 3,
    provider: str = "openai",
) -> list[dict]:
    """
    Generate new flashcards that expand on concepts from the current card.
    
    Args:
        api_key: API key for the selected provider
        question: The current card's question
        answer: The current card's answer
        concept_to_expand: Specific concept to expand (if empty, AI chooses)
        num_cards: Number of expansion cards to generate
        provider: "openai" or "anthropic"
        
    Returns:
        List of dicts with 'question' and 'answer' keys
    """
    system_prompt = """You are an expert educator creating flashcards to deepen understanding.

Given a flashcard, generate new cards that:
1. Break down complex concepts into smaller pieces
2. Explore prerequisites or foundational knowledge
3. Connect to related concepts or applications
4. Ask "why" and "how" questions, not just "what"

Each card should be self-contained and testable.
Keep questions concise but clear.
Answers should be thorough but focused.

Respond in JSON format:
{
    "cards": [
        {"question": "...", "answer": "...", "concept": "brief concept label"},
        ...
    ]
}"""

    user_prompt = f"""Generate {num_cards} expansion flashcards based on this card:

Question: {question}

Answer: {answer}

{f"Focus on expanding this concept: {concept_to_expand}" if concept_to_expand else "Choose the most important concepts to expand on."}

Generate cards that would help someone deeply understand this material."""

    if provider == "anthropic":
        client = get_anthropic_client(api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = json.loads(response.content[0].text)
    else:
        client = get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_completion_tokens=1500,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
    
    return result.get("cards", [])


def build_expansion_card_content(
    question: str,
    answer: str,
    source_card_id: str,
    concept: str = "",
) -> str:
    """
    Build markdown content for an expansion card.
    
    Args:
        question: The expansion question
        answer: The expansion answer
        source_card_id: ID of the original card
        concept: The concept this card expands on
        
    Returns:
        Markdown string for the new card
    """
    return f"""{question}

---

{answer}

<details>
<summary>🔗 Expanded from</summary>

{f"Concept: {concept}" if concept else ""}
Source card: `{source_card_id}`
</details>"""
