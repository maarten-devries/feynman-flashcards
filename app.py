"""
Feynman Flashcards - Socratic Review App

A Streamlit app that rephrases Mochi flashcard questions and uses AI
to evaluate answers with Socratic follow-ups, pushing for deep understanding.
"""

import os
import streamlit as st
import streamlit.components.v1 as components
import asyncio
from datetime import datetime
from dotenv import load_dotenv

import mochi
import ai

# Load environment variables from .env file
load_dotenv()

# Determine if we should collapse sidebar (auto-connect with cached keys)
_has_mochi_key = bool(os.getenv("MOCHI_API_KEY"))
_has_ai_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
_should_collapse_sidebar = _has_mochi_key and _has_ai_key

# Page config
st.set_page_config(
    page_title="Feynman Flashcards",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed" if _should_collapse_sidebar else "expanded",
)


def inject_keyboard_shortcuts():
    """Inject JavaScript for keyboard shortcuts (Cmd/Ctrl+Enter to submit)."""
    components.html("""
        <script>
        const doc = window.parent.document;
        
        doc.addEventListener('keydown', function(e) {
            // Cmd+Enter or Ctrl+Enter
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                
                // Try to find and click the submit/next button
                const buttons = doc.querySelectorAll('button[kind="primary"]');
                for (const btn of buttons) {
                    const text = btn.innerText.toLowerCase();
                    if (text.includes('submit') || text.includes('save') || text.includes('next') || text.includes('start') || text.includes('continue')) {
                        btn.click();
                        break;
                    }
                }
            }
            
            // Escape to skip
            if (e.key === 'Escape') {
                const buttons = doc.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.innerText.toLowerCase().includes('skip')) {
                        btn.click();
                        break;
                    }
                }
            }
        });
        </script>
    """, height=0)

# Initialize session state with .env defaults
if "mochi_key" not in st.session_state:
    st.session_state.mochi_key = os.getenv("MOCHI_API_KEY", "")
if "openai_key" not in st.session_state:
    st.session_state.openai_key = os.getenv("OPENAI_API_KEY", "")
if "anthropic_key" not in st.session_state:
    st.session_state.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
if "ai_provider" not in st.session_state:
    # Default to anthropic if we have that key, otherwise openai
    if os.getenv("ANTHROPIC_API_KEY"):
        st.session_state.ai_provider = "anthropic"
    else:
        st.session_state.ai_provider = "openai"
if "mochi_valid" not in st.session_state:
    st.session_state.mochi_valid = False
if "openai_valid" not in st.session_state:
    st.session_state.openai_valid = False
if "anthropic_valid" not in st.session_state:
    st.session_state.anthropic_valid = False
if "auto_connected" not in st.session_state:
    st.session_state.auto_connected = False
if "decks" not in st.session_state:
    st.session_state.decks = []
if "deck_tree" not in st.session_state:
    st.session_state.deck_tree = {}
if "current_cards" not in st.session_state:
    st.session_state.current_cards = []
if "current_card_index" not in st.session_state:
    st.session_state.current_card_index = 0
if "review_state" not in st.session_state:
    st.session_state.review_state = "idle"  # idle, question, answering, evaluating, follow_up, complete
if "rephrased_question" not in st.session_state:
    st.session_state.rephrased_question = ""
if "original_question" not in st.session_state:
    st.session_state.original_question = ""
if "original_answer" not in st.session_state:
    st.session_state.original_answer = ""
if "resolved_content" not in st.session_state:
    st.session_state.resolved_content = ""
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "current_evaluation" not in st.session_state:
    st.session_state.current_evaluation = None
if "follow_up_count" not in st.session_state:
    st.session_state.follow_up_count = 0
if "selected_deck_id" not in st.session_state:
    st.session_state.selected_deck_id = None
if "auto_submitted" not in st.session_state:
    st.session_state.auto_submitted = False
if "transcribed_answer" not in st.session_state:
    st.session_state.transcribed_answer = ""
if "last_audio_key" not in st.session_state:
    st.session_state.last_audio_key = None
if "source_url" not in st.session_state:
    st.session_state.source_url = None
if "source_content" not in st.session_state:
    st.session_state.source_content = None
if "use_source" not in st.session_state:
    st.session_state.use_source = False
if "source_cache" not in st.session_state:
    st.session_state.source_cache = {}  # URL -> content cache


def run_async(coro):
    """Helper to run async functions in Streamlit."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============ Auto-connect on startup if keys are in .env ============

if not st.session_state.auto_connected:
    st.session_state.auto_connected = True
    
    # Assume keys work and mark as valid (skip validation calls)
    mochi_key = st.session_state.mochi_key
    openai_key = st.session_state.openai_key
    anthropic_key = st.session_state.anthropic_key
    ai_provider = st.session_state.ai_provider
    
    if mochi_key:
        st.session_state.mochi_valid = True
        st.session_state.decks = run_async(mochi.get_decks(mochi_key))
        st.session_state.deck_tree = mochi.build_deck_tree(st.session_state.decks)
    
    if ai_provider == "openai" and openai_key:
        st.session_state.openai_valid = True
    elif ai_provider == "anthropic" and anthropic_key:
        st.session_state.anthropic_valid = True
        if openai_key:
            st.session_state.openai_valid = True


# ============ Sidebar: API Keys & Settings ============

with st.sidebar:
    st.title("🔑 API Keys")
    st.caption("Keys are stored in your browser only")
    
    # Try to load from local storage
    try:
        from streamlit_local_storage import LocalStorage
        local_storage = LocalStorage()
        
        stored_mochi = local_storage.getItem("mochi_key")
        stored_openai = local_storage.getItem("openai_key")
        stored_anthropic = local_storage.getItem("anthropic_key")
        stored_provider = local_storage.getItem("ai_provider")
        
        if stored_mochi and not st.session_state.mochi_key:
            st.session_state.mochi_key = stored_mochi
        if stored_openai and not st.session_state.openai_key:
            st.session_state.openai_key = stored_openai
        if stored_anthropic and not st.session_state.anthropic_key:
            st.session_state.anthropic_key = stored_anthropic
        if stored_provider and st.session_state.ai_provider == "openai":
            st.session_state.ai_provider = stored_provider
    except Exception:
        local_storage = None
    
    # Mochi API Key
    mochi_key = st.text_input(
        "Mochi API Key",
        value=st.session_state.mochi_key,
        type="password",
        help="Get your key at app.mochi.cards → Settings → API",
    )
    
    # AI Provider selection
    st.divider()
    st.subheader("🤖 AI Provider")
    ai_provider = st.radio(
        "Select AI Provider",
        options=["openai", "anthropic"],
        format_func=lambda x: "OpenAI (GPT-5.2)" if x == "openai" else "Anthropic (Claude)",
        index=0 if st.session_state.ai_provider == "openai" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state.ai_provider = ai_provider
    
    # Show appropriate API key input based on provider
    if ai_provider == "openai":
        openai_key = st.text_input(
            "OpenAI API Key",
            value=st.session_state.openai_key,
            type="password",
            help="Get your key at platform.openai.com/api-keys",
        )
        anthropic_key = st.session_state.anthropic_key
    else:
        anthropic_key = st.text_input(
            "Anthropic API Key",
            value=st.session_state.anthropic_key,
            type="password",
            help="Get your key at console.anthropic.com/settings/keys",
        )
        openai_key = st.session_state.openai_key
    
    # Note about voice features - OpenAI key needed for TTS/STT regardless of AI provider
    if ai_provider == "anthropic":
        st.caption("ℹ️ Voice features require OpenAI for TTS/STT (optional)")
        openai_voice_key = st.text_input(
            "OpenAI Key (for voice features)",
            value=st.session_state.openai_key,
            type="password",
            help="Optional - enables voice mode with Claude",
        )
        openai_key = openai_voice_key
    
    # Validate button
    if st.button("Connect", use_container_width=True):
        st.session_state.mochi_key = mochi_key
        st.session_state.openai_key = openai_key
        st.session_state.anthropic_key = anthropic_key
        st.session_state.ai_provider = ai_provider
        
        # Save to local storage
        if local_storage:
            try:
                local_storage.setItem("mochi_key", mochi_key)
                local_storage.setItem("openai_key", openai_key)
                local_storage.setItem("anthropic_key", anthropic_key)
                local_storage.setItem("ai_provider", ai_provider)
            except Exception:
                pass
        
        # Validate Mochi
        with st.spinner("Validating Mochi..."):
            mochi_ok, mochi_msg = run_async(mochi.validate_api_key(mochi_key))
            st.session_state.mochi_valid = mochi_ok
            if mochi_ok:
                st.success(mochi_msg)
                # Fetch decks
                st.session_state.decks = run_async(mochi.get_decks(mochi_key))
                st.session_state.deck_tree = mochi.build_deck_tree(st.session_state.decks)
            else:
                st.error(mochi_msg)
        
        # Validate AI provider
        if ai_provider == "openai":
            with st.spinner("Validating OpenAI..."):
                openai_ok, openai_msg = run_async(ai.validate_openai_key(openai_key))
                st.session_state.openai_valid = openai_ok
                st.session_state.anthropic_valid = False
                if openai_ok:
                    st.success(openai_msg)
                else:
                    st.error(openai_msg)
        else:
            with st.spinner("Validating Anthropic..."):
                anthropic_ok, anthropic_msg = run_async(ai.validate_anthropic_key(anthropic_key))
                st.session_state.anthropic_valid = anthropic_ok
                st.session_state.openai_valid = False
                if anthropic_ok:
                    st.success(anthropic_msg)
                else:
                    st.error(anthropic_msg)
            # Also validate OpenAI if provided (for voice features)
            if openai_key:
                with st.spinner("Validating OpenAI (voice)..."):
                    openai_ok, _ = run_async(ai.validate_openai_key(openai_key))
                    st.session_state.openai_valid = openai_ok
    
    # Status indicators
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.mochi_valid:
            st.success("Mochi ✓", icon="✅")
        else:
            st.error("Mochi ✗", icon="❌")
    with col2:
        # Show status for the selected provider
        if st.session_state.ai_provider == "openai":
            if st.session_state.openai_valid:
                st.success("OpenAI ✓", icon="✅")
            else:
                st.error("OpenAI ✗", icon="❌")
        else:
            if st.session_state.anthropic_valid:
                st.success("Claude ✓", icon="✅")
            else:
                st.error("Claude ✗", icon="❌")
    

    
    # Deck selection (optional - for specific deck review)
    st.divider()
    st.subheader("📚 Review Specific Deck")
    
    # Build deck options
    deck_options = {}
    for deck in st.session_state.decks:
        display_name = mochi.get_deck_display_name(deck, st.session_state.deck_tree)
        deck_options[display_name] = deck["id"]
    
    if deck_options:
        sorted_deck_names = sorted(deck_options.keys())
        selected_display = st.selectbox(
            "Choose a deck",
            options=sorted_deck_names,
            label_visibility="collapsed",
        )
        
        selected_deck_id = deck_options[selected_display]
        
        review_mode = st.radio(
            "Review mode",
            ["Due cards only", "All cards"],
            horizontal=True,
            label_visibility="collapsed",
        )
        
        if st.button("Review This Deck", use_container_width=True):
            with st.spinner("Fetching cards..."):
                if review_mode == "Due cards only":
                    cards = run_async(mochi.get_due_cards(st.session_state.mochi_key, selected_deck_id))
                else:
                    cards = run_async(mochi.get_cards_by_deck(st.session_state.mochi_key, selected_deck_id))
                
                if not cards:
                    st.info("No cards found!")
                else:
                    st.session_state.current_cards = cards
                    st.session_state.current_card_index = 0
                    st.session_state.review_state = "question"
                    st.session_state.conversation_history = []
                    st.session_state.follow_up_count = 0
                    st.session_state.selected_deck_id = selected_deck_id
                    st.rerun()
    
    # Links
    st.divider()
    st.caption("Need API keys?")
    st.markdown("[Get Mochi key](https://mochi.cards)")
    st.markdown("[Get OpenAI key](https://platform.openai.com/api-keys)")
    st.markdown("[Get Anthropic key](https://console.anthropic.com/settings/keys)")


# ============ Main Content ============

# Inject keyboard shortcuts
inject_keyboard_shortcuts()

# Check if connected
ai_valid = (
    (st.session_state.ai_provider == "openai" and st.session_state.openai_valid) or
    (st.session_state.ai_provider == "anthropic" and st.session_state.anthropic_valid)
)
if not (st.session_state.mochi_valid and ai_valid):
    st.info("👈 Enter your API keys in the sidebar to get started")
    st.stop()


# Helper to get current AI key and provider
def get_ai_config():
    """Return (api_key, provider) tuple for current AI provider."""
    if st.session_state.ai_provider == "anthropic":
        return st.session_state.anthropic_key, "anthropic"
    return st.session_state.openai_key, "openai"


# ============ Auto-start Due Cards Review ============

if st.session_state.review_state == "idle":
    # Auto-fetch due cards on first load
    with st.spinner("Loading due cards..."):
        cards = run_async(mochi.get_due_cards(st.session_state.mochi_key))
        
        if not cards:
            st.success("🎉 No cards due for review!")
            st.info("Select a specific deck from the sidebar to review all cards.")
            st.stop()
        else:
            st.session_state.current_cards = cards
            st.session_state.current_card_index = 0
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.follow_up_count = 0
            st.session_state.selected_deck_id = None  # All decks
            st.rerun()


# ============ Review Session ============

def start_new_card():
    """Initialize state for reviewing the current card."""
    card = st.session_state.current_cards[st.session_state.current_card_index]
    content = card.get("content", "")
    card_id = card.get("id", "")
    
    # Resolve images in content
    with st.spinner("Loading card..."):
        resolved_content = run_async(
            mochi.resolve_card_images(st.session_state.mochi_key, card_id, content)
        )
    
    # Parse question, answer, and source
    question, answer, source_url = ai.parse_card_content(resolved_content)
    st.session_state.original_question = question
    st.session_state.original_answer = answer
    st.session_state.resolved_content = resolved_content  # Store for display
    st.session_state.source_url = source_url
    
    # Auto-load source content from cache if available (no re-fetch needed)
    if source_url and source_url in st.session_state.source_cache:
        st.session_state.source_content = st.session_state.source_cache[source_url]
        st.session_state.use_source = True  # Auto-enable if cached
    else:
        st.session_state.source_content = None
        st.session_state.use_source = False
    
    # Generate rephrased question
    with st.spinner("Rephrasing question..."):
        ai_key, ai_provider = get_ai_config()
        rephrased = ai.rephrase_question(
            ai_key,
            question,
            answer,
            provider=ai_provider,
        )
        st.session_state.rephrased_question = rephrased
    
    st.session_state.conversation_history = []
    st.session_state.current_evaluation = None
    st.session_state.follow_up_count = 0
    st.session_state.transcribed_answer = ""
    st.session_state.last_audio_key = None


def play_audio(text: str):
    """Play text as speech if OpenAI key is available."""
    if st.session_state.openai_key and text and text.strip():
        try:
            audio_bytes = ai.text_to_speech(st.session_state.openai_key, text.strip())
            if audio_bytes:
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
        except Exception as e:
            # Silently fail for TTS - don't interrupt the user
            pass


if st.session_state.review_state in ["question", "answering", "follow_up"]:
    # Progress indicator
    total = len(st.session_state.current_cards)
    current = st.session_state.current_card_index + 1
    st.progress(current / total, text=f"Card {current} of {total}")
    
    # Initialize card if needed
    if not st.session_state.rephrased_question:
        start_new_card()
        st.rerun()
    
    # Display question
    st.subheader("Question")
    
    # Show follow-up question if in follow-up state
    if st.session_state.review_state == "follow_up" and st.session_state.current_evaluation:
        follow_up = st.session_state.current_evaluation.get("follow_up", "")
        if follow_up:
            st.info(f"🤔 {follow_up}")
            if st.session_state.openai_key and "played_follow_up" not in st.session_state:
                play_audio(follow_up)
                st.session_state.played_follow_up = True
    else:
        st.info(f"🎯 {st.session_state.rephrased_question}")
        if st.session_state.openai_key and st.session_state.review_state == "question":
            if "played_question" not in st.session_state:
                play_audio(st.session_state.rephrased_question)
                st.session_state.played_question = True
    
    # Show original question (front of card only, with images)
    with st.expander("📄 Show Original Question", expanded=False):
        st.markdown(st.session_state.original_question, unsafe_allow_html=True)
    
    # Source toggle - only show if card has a source URL
    if st.session_state.source_url:
        col_source, col_status = st.columns([3, 1])
        with col_source:
            use_source = st.toggle(
                "📚 Use Source Context",
                value=st.session_state.use_source,
                help=f"Include content from source in AI conversation: {st.session_state.source_url}",
            )
            if use_source != st.session_state.use_source:
                st.session_state.use_source = use_source
                # Fetch source content if toggled on and not cached
                if use_source and not st.session_state.source_content:
                    url = st.session_state.source_url
                    if url in st.session_state.source_cache:
                        st.session_state.source_content = st.session_state.source_cache[url]
                    else:
                        with st.spinner("Fetching source content..."):
                            content = run_async(ai.fetch_source_content(url))
                            if content:
                                st.session_state.source_content = content
                                st.session_state.source_cache[url] = content
                st.rerun()
        with col_status:
            if st.session_state.use_source:
                if st.session_state.source_content:
                    st.success("✓ Loaded", icon="📚")
                else:
                    st.warning("✗ Failed", icon="⚠️")
    
    # Show previous feedback if in follow-up
    if st.session_state.current_evaluation and st.session_state.review_state == "follow_up":
        with st.expander("Previous Feedback", expanded=False):
            st.write(st.session_state.current_evaluation.get("feedback", ""))
    
    # Answer input
    st.subheader("Your Answer")
    
    # Text input always available
    user_answer = st.text_area(
        "Type your answer",
        key=f"answer_input_{st.session_state.follow_up_count}",
        placeholder="Explain your understanding...",
        label_visibility="collapsed",
    )
    
    # Voice input always available
    audio_key = f"audio_input_{st.session_state.follow_up_count}"
    audio_input = st.audio_input(
        "🎤 Or speak your answer",
        key=audio_key,
    )
    
    voice_command_detected = None
    auto_submit_after_transcribe = False
    
    # Only transcribe if we have new audio (different key or new recording)
    if audio_input and st.session_state.last_audio_key != audio_key:
        st.session_state.last_audio_key = audio_key
        st.session_state.transcribed_answer = ""
        with st.spinner("Transcribing..."):
            try:
                transcribed = ai.transcribe_audio(
                    st.session_state.openai_key,
                    audio_input.getvalue(),
                    "audio.wav",
                )
                st.session_state.transcribed_answer = transcribed
                user_answer = transcribed
                
                # Check for voice commands
                lower_transcribed = transcribed.lower().strip()
                if lower_transcribed in ["skip", "skip card", "next card", "pass"]:
                    voice_command_detected = "skip"
                elif lower_transcribed in ["next", "continue", "go on"]:
                    voice_command_detected = "continue"
                else:
                    # Always auto-submit after transcription (no extra click needed)
                    auto_submit_after_transcribe = True
                
            except Exception as e:
                st.error(f"Transcription error: {e}")
    elif audio_input and st.session_state.transcribed_answer:
        # Use cached transcription
        user_answer = st.session_state.transcribed_answer
        st.success(f"Transcribed: {user_answer}")
    
    # Submit button
    col1, col2 = st.columns([3, 1])
    with col1:
        submit = st.button("Submit Answer", type="primary", use_container_width=True, disabled=not user_answer)
    with col2:
        skip = st.button("Skip", use_container_width=True)
    
    # Handle voice command: skip
    if voice_command_detected == "skip":
        st.session_state.auto_submitted = False
        st.session_state.transcribed_answer = ""
        st.session_state.last_audio_key = None
        st.session_state.current_card_index += 1
        st.session_state.rephrased_question = ""
        st.session_state.review_state = "question"
        st.session_state.pop("played_question", None)
        st.session_state.pop("played_follow_up", None)
        if st.session_state.current_card_index >= len(st.session_state.current_cards):
            st.session_state.review_state = "complete"
        st.rerun()
    
    # Auto-submit immediately after transcription in voice mode
    if auto_submit_after_transcribe and user_answer:
        submit = True
    
    if skip:
        # Move to next card
        st.session_state.auto_submitted = False
        st.session_state.transcribed_answer = ""
        st.session_state.last_audio_key = None
        st.session_state.current_card_index += 1
        st.session_state.rephrased_question = ""
        st.session_state.review_state = "question"
        st.session_state.pop("played_question", None)
        st.session_state.pop("played_follow_up", None)
        
        if st.session_state.current_card_index >= len(st.session_state.current_cards):
            st.session_state.review_state = "complete"
        st.rerun()
    
    if submit and user_answer:
        st.session_state.auto_submitted = False
        st.session_state.transcribed_answer = ""
        st.session_state.last_audio_key = None
        with st.spinner("Evaluating your answer..."):
            # Determine what question we're evaluating against
            if st.session_state.review_state == "follow_up" and st.session_state.current_evaluation:
                current_question = st.session_state.current_evaluation.get("follow_up", st.session_state.rephrased_question)
            else:
                current_question = st.session_state.rephrased_question
            
            ai_key, ai_provider = get_ai_config()
            
            # Include source content if enabled
            source_content = None
            if st.session_state.use_source and st.session_state.source_content:
                source_content = st.session_state.source_content
            
            evaluation = ai.evaluate_answer(
                ai_key,
                current_question,
                st.session_state.original_answer,
                user_answer,
                st.session_state.conversation_history if st.session_state.conversation_history else None,
                provider=ai_provider,
                source_content=source_content,
            )
            
            # Store in history
            st.session_state.conversation_history.append({
                "question": current_question,
                "user_answer": user_answer,
                "evaluation": evaluation,
            })
            
            st.session_state.current_evaluation = evaluation
            st.session_state.review_state = "evaluating"
            st.rerun()


# ============ Evaluation Display ============

if st.session_state.review_state == "evaluating":
    # Progress indicator
    total = len(st.session_state.current_cards)
    current = st.session_state.current_card_index + 1
    st.progress(current / total, text=f"Card {current} of {total}")
    
    eval_result = st.session_state.current_evaluation
    
    # Show score
    score = eval_result.get("score", 0)
    if score >= 0.8:
        st.success(f"✅ Great understanding! ({score:.0%})")
    elif score >= 0.5:
        st.warning(f"🤔 Partial understanding ({score:.0%})")
    else:
        st.error(f"❌ Needs work ({score:.0%})")
    
    # Show feedback
    st.subheader("Feedback")
    feedback = eval_result.get("feedback", "")
    st.write(feedback)
    
    if st.session_state.openai_key and "played_feedback" not in st.session_state:
        play_audio(feedback)
        st.session_state.played_feedback = True
    
    # Show original answer for reference (with images)
    with st.expander("📖 Expected Answer"):
        st.markdown(st.session_state.original_answer, unsafe_allow_html=True)
    
    # Show conversation history
    if len(st.session_state.conversation_history) > 1:
        with st.expander("💬 Conversation History"):
            for i, entry in enumerate(st.session_state.conversation_history):
                st.markdown(f"**Q{i+1}:** {entry['question']}")
                st.markdown(f"**A{i+1}:** {entry['user_answer']}")
                st.markdown(f"*{entry['evaluation'].get('feedback', '')}*")
                st.divider()
    
    # Determine next action
    follow_up = eval_result.get("follow_up")
    is_correct = eval_result.get("is_correct", False)
    max_follow_ups = 3
    
    # Voice input for navigation (always available when OpenAI key present)
    if st.session_state.openai_key:
        st.divider()
        st.caption("🎤 Voice commands: 'got it', 'again', 'skip', 'continue'")
        
        nav_audio = st.audio_input(
            "🎤 Or speak a command",
            key="nav_audio_eval",
        )
        
        if nav_audio:
            try:
                nav_transcribed = ai.transcribe_audio(
                    st.session_state.openai_key,
                    nav_audio.getvalue(),
                    "audio.wav",
                )
                nav_lower = nav_transcribed.lower().strip()
                st.caption(f"Heard: {nav_transcribed}")
                
                if nav_lower in ["got it", "good", "correct", "remembered", "yes", "next"]:
                    st.session_state.pending_action = "remembered"
                    st.rerun()
                elif nav_lower in ["again", "forgot", "wrong", "no", "repeat"]:
                    st.session_state.pending_action = "forgot"
                    st.rerun()
                elif nav_lower in ["skip", "pass", "skip card"]:
                    st.session_state.pending_action = "skip"
                    st.rerun()
                elif nav_lower in ["continue", "follow up", "follow-up", "more", "go on"] and follow_up:
                    st.session_state.pending_action = "continue"
                    st.rerun()
            except Exception as e:
                st.error(f"Voice error: {e}")
    
    # Handle pending actions from voice commands
    if "pending_action" in st.session_state:
        action = st.session_state.pop("pending_action")
        if action == "next" or action == "skip":
            st.session_state.current_card_index += 1
            st.session_state.rephrased_question = ""
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.chat_messages = []
            st.session_state.follow_up_count = 0
            st.session_state.transcribed_answer = ""
            st.session_state.last_audio_key = None
            st.session_state.pop("played_question", None)
            st.session_state.pop("played_feedback", None)
            if st.session_state.current_card_index >= len(st.session_state.current_cards):
                st.session_state.review_state = "complete"
            st.rerun()
        elif action == "continue":
            st.session_state.follow_up_count += 1
            st.session_state.transcribed_answer = ""
            st.session_state.last_audio_key = None
            st.session_state.review_state = "follow_up"
            st.session_state.pop("played_follow_up", None)
            st.session_state.pop("played_feedback", None)
            st.rerun()
        elif action == "remembered":
            # Mark as remembered and move to next
            card = st.session_state.current_cards[st.session_state.current_card_index]
            try:
                run_async(mochi.review_card(
                    st.session_state.mochi_key,
                    card.get("id"),
                    remembered=True,
                ))
            except:
                pass
            st.session_state.current_card_index += 1
            st.session_state.rephrased_question = ""
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.chat_messages = []
            st.session_state.follow_up_count = 0
            st.session_state.transcribed_answer = ""
            st.session_state.last_audio_key = None
            st.session_state.pop("played_question", None)
            st.session_state.pop("played_feedback", None)
            if st.session_state.current_card_index >= len(st.session_state.current_cards):
                st.session_state.review_state = "complete"
            st.rerun()
        elif action == "forgot":
            # Mark as forgot and move to next
            card = st.session_state.current_cards[st.session_state.current_card_index]
            try:
                run_async(mochi.review_card(
                    st.session_state.mochi_key,
                    card.get("id"),
                    remembered=False,
                ))
            except:
                pass
            st.session_state.current_card_index += 1
            st.session_state.rephrased_question = ""
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.chat_messages = []
            st.session_state.follow_up_count = 0
            st.session_state.transcribed_answer = ""
            st.session_state.last_audio_key = None
            st.session_state.pop("played_question", None)
            st.session_state.pop("played_feedback", None)
            if st.session_state.current_card_index >= len(st.session_state.current_cards):
                st.session_state.review_state = "complete"
            st.rerun()
    
    # Continue discussion button
    if follow_up and not is_correct and st.session_state.follow_up_count < max_follow_ups:
        if st.button("🔄 Continue Discussion", type="secondary", use_container_width=True):
            st.session_state.follow_up_count += 1
            st.session_state.review_state = "follow_up"
            st.session_state.pop("played_follow_up", None)
            st.rerun()
    
    # SRS Review buttons
    st.divider()
    st.subheader("📊 Mark Review")
    st.caption("Update Mochi's spaced repetition schedule")
    
    card = st.session_state.current_cards[st.session_state.current_card_index]
    card_id = card.get("id")
    
    def move_to_next():
        """Helper to move to next card."""
        st.session_state.current_card_index += 1
        st.session_state.rephrased_question = ""
        st.session_state.review_state = "question"
        st.session_state.conversation_history = []
        st.session_state.chat_messages = []
        st.session_state.follow_up_count = 0
        st.session_state.transcribed_answer = ""
        st.session_state.last_audio_key = None
        st.session_state.pop("played_question", None)
        st.session_state.pop("played_feedback", None)
        st.session_state.pop("pending_card_suggestion", None)
        if st.session_state.current_card_index >= len(st.session_state.current_cards):
            st.session_state.review_state = "complete"
    
    col_good, col_again, col_skip = st.columns(3)
    
    with col_good:
        if st.button("✅ Got it!", type="primary", use_container_width=True, help="Mark as remembered - increases interval"):
            with st.spinner("Marking review..."):
                try:
                    run_async(mochi.review_card(
                        st.session_state.mochi_key,
                        card_id,
                        remembered=True,
                    ))
                    st.toast("✅ Marked as remembered!", icon="✅")
                except Exception as e:
                    st.error(f"Failed to mark review: {e}")
            move_to_next()
            st.rerun()
    
    with col_again:
        if st.button("🔁 Again", use_container_width=True, help="Mark as forgotten - resets interval"):
            with st.spinner("Marking review..."):
                try:
                    run_async(mochi.review_card(
                        st.session_state.mochi_key,
                        card_id,
                        remembered=False,
                    ))
                    st.toast("🔁 Marked for review again", icon="🔁")
                except Exception as e:
                    st.error(f"Failed to mark review: {e}")
            move_to_next()
            st.rerun()
    
    with col_skip:
        if st.button("⏭️ Skip", use_container_width=True, help="Skip without marking in Mochi"):
            move_to_next()
            st.rerun()
    
    # ============ Chat Interface ============
    st.divider()
    st.subheader("💬 Chat & Explore")
    st.caption("Ask follow-up questions, clarify concepts, or discuss modifications")
    
    # Initialize chat messages in session state
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    
    # Display chat history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    # Chat input - text and voice
    chat_input = st.chat_input("Ask a question about this topic...")
    
    # Voice input for chat
    chat_audio_key = f"chat_audio_{st.session_state.current_card_index}_{len(st.session_state.chat_messages)}"
    chat_audio = st.audio_input("🎤 Or ask with voice", key=chat_audio_key)
    
    # Transcribe voice chat input if provided
    if chat_audio and st.session_state.openai_key:
        if f"transcribed_{chat_audio_key}" not in st.session_state:
            with st.spinner("Transcribing..."):
                try:
                    transcribed_chat = ai.transcribe_audio(
                        st.session_state.openai_key,
                        chat_audio.getvalue(),
                        "audio.wav",
                    )
                    st.session_state[f"transcribed_{chat_audio_key}"] = transcribed_chat
                    chat_input = transcribed_chat
                except Exception as e:
                    st.error(f"Transcription error: {e}")
        else:
            chat_input = st.session_state[f"transcribed_{chat_audio_key}"]
    
    if chat_input:
        # Add user message
        st.session_state.chat_messages.append({"role": "user", "content": chat_input})
        
        # Get AI response
        with st.spinner("Thinking..."):
            try:
                ai_key, ai_provider = get_ai_config()
                
                # Include source content if enabled
                source_content = None
                if st.session_state.use_source and st.session_state.source_content:
                    source_content = st.session_state.source_content
                
                response = ai.chat_followup(
                    ai_key,
                    st.session_state.chat_messages,
                    st.session_state.original_question,
                    st.session_state.original_answer,
                    chat_input,
                    provider=ai_provider,
                    source_content=source_content,
                )
                st.session_state.chat_messages.append({"role": "assistant", "content": response})
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
    
    # ============ Card Actions ============
    st.divider()
    with st.expander("✏️ Modify or Add Cards", expanded=False):
        st.caption("Update this card or create a new one based on your learning")
        
        card = st.session_state.current_cards[st.session_state.current_card_index]
        deck_id = card.get("deck-id")
        card_id = card.get("id", "unknown")
        
        col_mod, col_add = st.columns(2)
        
        with col_mod:
            if st.button("📝 Suggest Modification", use_container_width=True):
                with st.spinner("Analyzing conversation..."):
                    try:
                        ai_key, ai_provider = get_ai_config()
                        suggestion = ai.suggest_card_modification(
                            ai_key,
                            st.session_state.original_question,
                            st.session_state.original_answer,
                            st.session_state.chat_messages,
                            provider=ai_provider,
                        )
                        st.session_state.pending_modification = suggestion
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        
        with col_add:
            if st.button("➕ Suggest New Card", use_container_width=True):
                with st.spinner("Creating new card suggestion..."):
                    try:
                        ai_key, ai_provider = get_ai_config()
                        suggestion = ai.suggest_new_card(
                            ai_key,
                            st.session_state.original_question,
                            st.session_state.original_answer,
                            st.session_state.chat_messages,
                            provider=ai_provider,
                        )
                        st.session_state.pending_new_card = suggestion
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        
        # Show modification suggestion
        if "pending_modification" in st.session_state and st.session_state.pending_modification:
            st.subheader("Suggested Modification")
            mod = st.session_state.pending_modification
            
            st.markdown("**Question:**")
            mod_question = st.text_area(
                "Edit question",
                value=mod.get("question", st.session_state.original_question),
                key="mod_question",
                label_visibility="collapsed",
            )
            
            st.markdown("**Answer:**")
            mod_answer = st.text_area(
                "Edit answer",
                value=mod.get("answer", st.session_state.original_answer),
                key="mod_answer",
                label_visibility="collapsed",
            )
            
            col_save_mod, col_cancel_mod = st.columns(2)
            with col_save_mod:
                if st.button("💾 Save Changes to Card", type="primary", use_container_width=True):
                    with st.spinner("Updating card..."):
                        try:
                            new_content = f"{mod_question}\n\n---\n\n{mod_answer}"
                            run_async(mochi.update_card_content(
                                st.session_state.mochi_key,
                                card_id,
                                new_content,
                            ))
                            st.success("Card updated!")
                            st.session_state.pending_modification = None
                            # Update local copy
                            st.session_state.original_question = mod_question
                            st.session_state.original_answer = mod_answer
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating card: {e}")
            
            with col_cancel_mod:
                if st.button("❌ Cancel", key="cancel_mod", use_container_width=True):
                    st.session_state.pending_modification = None
                    st.rerun()
        
        # Show new card suggestion
        if "pending_new_card" in st.session_state and st.session_state.pending_new_card:
            st.subheader("New Card Preview")
            new_card = st.session_state.pending_new_card
            
            st.markdown("**Question:**")
            new_question = st.text_area(
                "Edit question",
                value=new_card.get("question", ""),
                key="new_question",
                label_visibility="collapsed",
            )
            
            st.markdown("**Answer:**")
            new_answer = st.text_area(
                "Edit answer",
                value=new_card.get("answer", ""),
                key="new_answer",
                label_visibility="collapsed",
            )
            
            col_save_new, col_cancel_new = st.columns(2)
            with col_save_new:
                if st.button("💾 Add Card to Deck", type="primary", use_container_width=True):
                    with st.spinner("Creating card..."):
                        try:
                            card_content = f"{new_question}\n\n---\n\n{new_answer}"
                            run_async(mochi.create_card(
                                st.session_state.mochi_key,
                                deck_id,
                                card_content,
                            ))
                            st.success("New card created!")
                            st.session_state.pending_new_card = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error creating card: {e}")
            
            with col_cancel_new:
                if st.button("❌ Cancel", key="cancel_new", use_container_width=True):
                    st.session_state.pending_new_card = None
                    st.rerun()
    
    # Expand concepts section
    with st.expander("🔬 Expand on concepts", expanded=False):
        st.caption("Generate new cards that dive deeper into concepts from this card")
        
        concept_input = st.text_input(
            "Specific concept to expand (optional)",
            placeholder="Leave empty to auto-select key concepts",
            key="concept_to_expand",
        )
        
        num_expansion = st.slider("Number of cards to generate", 1, 5, 3)
        
        if st.button("Generate Expansion Cards", type="secondary", use_container_width=True):
            with st.spinner("Generating expansion cards..."):
                try:
                    ai_key, ai_provider = get_ai_config()
                    expansion_cards = ai.generate_expansion_cards(
                        ai_key,
                        st.session_state.original_question,
                        st.session_state.original_answer,
                        concept_to_expand=concept_input,
                        num_cards=num_expansion,
                        provider=ai_provider,
                    )
                    
                    if expansion_cards:
                        st.session_state.pending_expansions = expansion_cards
                        st.success(f"Generated {len(expansion_cards)} expansion cards!")
                        st.rerun()
                    else:
                        st.warning("No expansion cards generated")
                except Exception as e:
                    st.error(f"Error generating cards: {e}")
        
        # Show pending expansion cards for review
        if "pending_expansions" in st.session_state and st.session_state.pending_expansions:
            st.subheader("Preview Expansion Cards")
            
            cards_to_save = []
            for i, exp_card in enumerate(st.session_state.pending_expansions):
                with st.container(border=True):
                    st.markdown(f"**Card {i+1}:** {exp_card.get('concept', 'Expansion')}")
                    st.markdown(f"**Q:** {exp_card['question']}")
                    st.markdown(f"**A:** {exp_card['answer']}")
                    if st.checkbox(f"Include card {i+1}", value=True, key=f"include_exp_{i}"):
                        cards_to_save.append(exp_card)
            
            if st.button("Save Selected Expansion Cards", type="primary", use_container_width=True):
                with st.spinner("Saving expansion cards..."):
                    try:
                        card = st.session_state.current_cards[st.session_state.current_card_index]
                        deck_id = card.get("deck-id")
                        card_id = card.get("id", "unknown")
                        
                        # Create each expansion card in the same deck
                        created_ids = []
                        for exp_card in cards_to_save:
                            card_content = ai.build_expansion_card_content(
                                exp_card["question"],
                                exp_card["answer"],
                                card_id,
                                exp_card.get("concept", ""),
                            )
                            
                            new_card = run_async(mochi.create_card(
                                st.session_state.mochi_key,
                                deck_id,
                                card_content,
                                tags=["expansion"],
                            ))
                            created_ids.append(new_card.get("id", "unknown"))
                        
                        # Update original card to link to expansions
                        original_content = card.get("content", "")
                        links_section = "\n\n<details>\n<summary>🔗 Expansion cards</summary>\n\n"
                        for exp_id in created_ids:
                            links_section += f"- `{exp_id}`\n"
                        links_section += "</details>"
                        
                        # Only add if not already there
                        if "🔗 Expansion cards" not in original_content:
                            run_async(mochi.update_card_content(
                                st.session_state.mochi_key,
                                card_id,
                                original_content + links_section,
                            ))
                        
                        st.success(f"Saved {len(cards_to_save)} expansion cards!")
                        st.session_state.pending_expansions = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving cards: {e}")


# ============ Session Complete ============

if st.session_state.review_state == "complete":
    st.balloons()
    st.success("🎉 Review session complete!")
    
    st.subheader("Session Summary")
    st.write(f"Cards reviewed: {len(st.session_state.current_cards)}")
    
    if st.button("Start New Session", type="primary", use_container_width=True):
        st.session_state.review_state = "idle"
        st.session_state.current_cards = []
        st.session_state.current_card_index = 0
        st.session_state.rephrased_question = ""
        st.session_state.conversation_history = []
        st.session_state.chat_messages = []
        st.rerun()
