"""
OpenAI Service Module

Provides functions for:
- Rephrasing flashcard questions
- Evaluating user answers with Socratic follow-ups
- Speech-to-text transcription
- Text-to-speech synthesis
"""

import json
from openai import OpenAI
from typing import Optional


def get_client(api_key: str) -> OpenAI:
    """Create OpenAI client with user's API key."""
    return OpenAI(api_key=api_key)


async def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Validate an OpenAI API key by listing models.
    
    Returns:
        (success, message) tuple
    """
    try:
        client = get_client(api_key)
        # Simple validation - list models
        client.models.list()
        return True, "Connected to OpenAI"
    except Exception as e:
        error_msg = str(e)
        if "invalid_api_key" in error_msg.lower() or "401" in error_msg:
            return False, "Invalid API key"
        return False, f"Connection error: {error_msg[:100]}"


def parse_card_content(content: str) -> tuple[str, str]:
    """
    Parse Mochi card content into question and answer.
    
    Mochi cards typically use --- to separate front/back,
    or use template fields like << Front >> and << Back >>.
    
    Returns:
        (question, answer) tuple
    """
    # Handle --- separator (most common)
    if "---" in content:
        parts = content.split("---", 1)
        question = parts[0].strip()
        answer = parts[1].strip() if len(parts) > 1 else ""
        # Clean up markdown headers
        question = question.lstrip("#").strip()
        return question, answer
    
    # Handle << Field >> template syntax
    if "<<" in content and ">>" in content:
        # This is a template card - just use the whole content
        return content, ""
    
    # Fallback: treat first line as question, rest as answer
    lines = content.strip().split("\n", 1)
    question = lines[0].lstrip("#").strip()
    answer = lines[1].strip() if len(lines) > 1 else ""
    return question, answer


def rephrase_question(api_key: str, question: str, answer: str, context: str = "") -> str:
    """
    Generate a rephrased version of a flashcard question.
    
    The rephrasing preserves the core concept being tested but uses
    different wording, context, or framing to prevent pattern memorization.
    
    Args:
        api_key: OpenAI API key
        question: Original question from the card
        answer: Expected answer (to preserve difficulty)
        context: Optional additional context about the topic
        
    Returns:
        Rephrased question string
    """
    client = get_client(api_key)
    
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

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=300,
    )
    
    return response.choices[0].message.content.strip()


def evaluate_answer(
    api_key: str,
    question: str,
    expected_answer: str,
    user_answer: str,
    conversation_history: Optional[list[dict]] = None,
) -> dict:
    """
    Evaluate a user's answer and provide Socratic feedback.
    
    Args:
        api_key: OpenAI API key
        question: The question that was asked
        expected_answer: The correct/expected answer
        user_answer: What the user provided
        conversation_history: Previous exchanges for follow-up context
        
    Returns:
        Dict with:
        - is_correct: bool - whether understanding is demonstrated
        - score: float 0-1 - confidence in correctness
        - feedback: str - explanation of what's right/wrong
        - follow_up: str|None - follow-up question if needed
    """
    client = get_client(api_key)
    
    system_prompt = """You are a Socratic tutor evaluating student understanding.

Your role is to:
1. Assess if the student's answer demonstrates understanding of the core concept
2. Provide constructive feedback
3. If understanding is incomplete, ask a follow-up question to probe deeper

Be encouraging but honest. Focus on conceptual understanding, not exact wording.
A partially correct answer should get a follow-up question to clarify gaps.

Respond in JSON format:
{
    "is_correct": true/false,
    "score": 0.0-1.0,
    "feedback": "Your explanation of what's right/wrong",
    "follow_up": "A follow-up question if needed, or null if understanding is complete"
}"""

    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history if this is a follow-up
    if conversation_history:
        for entry in conversation_history:
            messages.append({"role": "assistant", "content": json.dumps(entry["evaluation"])})
            messages.append({"role": "user", "content": f"Student's response: {entry['user_answer']}"})
    
    # Current evaluation request
    user_prompt = f"""Question asked: {question}

Expected answer: {expected_answer}

Student's answer: {user_answer}

Evaluate this answer and respond in JSON format."""

    messages.append({"role": "user", "content": user_prompt})
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
        max_tokens=500,
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


def transcribe_audio(api_key: str, audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Transcribe audio to text using OpenAI's speech-to-text.
    
    Args:
        api_key: OpenAI API key
        audio_bytes: Raw audio bytes
        filename: Filename hint for format detection
        
    Returns:
        Transcribed text
    """
    client = get_client(api_key)
    
    # Create a file-like object from bytes
    response = client.audio.transcriptions.create(
        model="gpt-4o-transcribe",
        file=(filename, audio_bytes),
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


def build_feynman_card_content(
    original_question: str,
    original_answer: str,
    rephrased_question: str,
    source_card_id: str,
) -> str:
    """
    Build markdown content for a new Feynman card.
    
    Args:
        original_question: The original question
        original_answer: The expected answer
        rephrased_question: The AI-generated rephrased question
        source_card_id: ID of the original card for reference
        
    Returns:
        Markdown string for the new card
    """
    return f"""{rephrased_question}

---

{original_answer}

<details>
<summary>📝 Source</summary>

Original: {original_question}

Card ID: `{source_card_id}`
</details>"""
