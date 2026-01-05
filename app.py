"""
Feynman Flashcards - Socratic Review App

A Streamlit app that rephrases Mochi flashcard questions and uses AI
to evaluate answers with Socratic follow-ups, pushing for deep understanding.
"""

import os
import streamlit as st
import asyncio
from datetime import datetime
from dotenv import load_dotenv

import mochi
import ai

# Load environment variables from .env file
load_dotenv()

# Page config
st.set_page_config(
    page_title="Feynman Flashcards",
    page_icon="🧠",
    layout="centered",
)

# Initialize session state with .env defaults
if "mochi_key" not in st.session_state:
    st.session_state.mochi_key = os.getenv("MOCHI_API_KEY", "")
if "openai_key" not in st.session_state:
    st.session_state.openai_key = os.getenv("OPENAI_API_KEY", "")
if "mochi_valid" not in st.session_state:
    st.session_state.mochi_valid = False
if "openai_valid" not in st.session_state:
    st.session_state.openai_valid = False
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
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "current_evaluation" not in st.session_state:
    st.session_state.current_evaluation = None
if "follow_up_count" not in st.session_state:
    st.session_state.follow_up_count = 0
if "voice_mode" not in st.session_state:
    st.session_state.voice_mode = False
if "selected_deck_id" not in st.session_state:
    st.session_state.selected_deck_id = None


def run_async(coro):
    """Helper to run async functions in Streamlit."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
        
        if stored_mochi and not st.session_state.mochi_key:
            st.session_state.mochi_key = stored_mochi
        if stored_openai and not st.session_state.openai_key:
            st.session_state.openai_key = stored_openai
    except Exception:
        local_storage = None
    
    # Mochi API Key
    mochi_key = st.text_input(
        "Mochi API Key",
        value=st.session_state.mochi_key,
        type="password",
        help="Get your key at app.mochi.cards → Settings → API",
    )
    
    # OpenAI API Key  
    openai_key = st.text_input(
        "OpenAI API Key",
        value=st.session_state.openai_key,
        type="password",
        help="Get your key at platform.openai.com/api-keys",
    )
    
    # Validate button
    if st.button("Connect", use_container_width=True):
        st.session_state.mochi_key = mochi_key
        st.session_state.openai_key = openai_key
        
        # Save to local storage
        if local_storage:
            try:
                local_storage.setItem("mochi_key", mochi_key)
                local_storage.setItem("openai_key", openai_key)
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
        
        # Validate OpenAI
        with st.spinner("Validating OpenAI..."):
            openai_ok, openai_msg = run_async(ai.validate_api_key(openai_key))
            st.session_state.openai_valid = openai_ok
            if openai_ok:
                st.success(openai_msg)
            else:
                st.error(openai_msg)
    
    # Status indicators
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.mochi_valid:
            st.success("Mochi ✓", icon="✅")
        else:
            st.error("Mochi ✗", icon="❌")
    with col2:
        if st.session_state.openai_valid:
            st.success("OpenAI ✓", icon="✅")
        else:
            st.error("OpenAI ✗", icon="❌")
    
    # Voice mode toggle
    st.divider()
    st.session_state.voice_mode = st.toggle(
        "🔊 Voice Mode",
        value=st.session_state.voice_mode,
        help="Enable text-to-speech for questions and feedback",
    )
    
    # Links
    st.divider()
    st.caption("Need API keys?")
    st.markdown("[Get Mochi key](https://app.mochi.cards/settings/api)")
    st.markdown("[Get OpenAI key](https://platform.openai.com/api-keys)")


# ============ Main Content ============

st.title("🧠 Feynman Flashcards")
st.caption("Deep practice through AI-rephrased questions and Socratic dialogue")

# Check if connected
if not (st.session_state.mochi_valid and st.session_state.openai_valid):
    st.info("👈 Enter your API keys in the sidebar to get started")
    st.stop()


# ============ Deck Selection ============

if st.session_state.review_state == "idle":
    st.subheader("Select a Deck")
    
    # Build deck options
    deck_options = {}
    for deck in st.session_state.decks:
        # Skip Feynman subdecks
        if deck.get("name") == "Feynman":
            continue
        display_name = mochi.get_deck_display_name(deck, st.session_state.deck_tree)
        deck_options[display_name] = deck["id"]
    
    if not deck_options:
        st.warning("No decks found in your Mochi account")
        st.stop()
    
    selected_display = st.selectbox(
        "Choose a deck to review",
        options=list(deck_options.keys()),
    )
    
    selected_deck_id = deck_options[selected_display]
    st.session_state.selected_deck_id = selected_deck_id
    
    # Fetch due cards count
    if st.button("Start Review", type="primary", use_container_width=True):
        with st.spinner("Fetching due cards..."):
            cards = run_async(mochi.get_due_cards(st.session_state.mochi_key, selected_deck_id))
            
            if not cards:
                st.info("🎉 No cards due for review in this deck!")
            else:
                st.session_state.current_cards = cards
                st.session_state.current_card_index = 0
                st.session_state.review_state = "question"
                st.session_state.conversation_history = []
                st.session_state.follow_up_count = 0
                st.rerun()


# ============ Review Session ============

def start_new_card():
    """Initialize state for reviewing the current card."""
    card = st.session_state.current_cards[st.session_state.current_card_index]
    content = card.get("content", "")
    
    # Parse question and answer
    question, answer = ai.parse_card_content(content)
    st.session_state.original_question = question
    st.session_state.original_answer = answer
    
    # Generate rephrased question
    with st.spinner("Rephrasing question..."):
        rephrased = ai.rephrase_question(
            st.session_state.openai_key,
            question,
            answer,
        )
        st.session_state.rephrased_question = rephrased
    
    st.session_state.conversation_history = []
    st.session_state.current_evaluation = None
    st.session_state.follow_up_count = 0


def play_audio(text: str):
    """Play text as speech if voice mode is enabled."""
    if st.session_state.voice_mode:
        try:
            audio_bytes = ai.text_to_speech(st.session_state.openai_key, text)
            st.audio(audio_bytes, format="audio/mp3", autoplay=True)
        except Exception as e:
            st.warning(f"TTS error: {e}")


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
            if st.session_state.voice_mode and "played_follow_up" not in st.session_state:
                play_audio(follow_up)
                st.session_state.played_follow_up = True
    else:
        st.info(f"🎯 {st.session_state.rephrased_question}")
        if st.session_state.voice_mode and st.session_state.review_state == "question":
            if "played_question" not in st.session_state:
                play_audio(st.session_state.rephrased_question)
                st.session_state.played_question = True
    
    # Show previous feedback if in follow-up
    if st.session_state.current_evaluation and st.session_state.review_state == "follow_up":
        with st.expander("Previous Feedback", expanded=False):
            st.write(st.session_state.current_evaluation.get("feedback", ""))
    
    # Answer input
    st.subheader("Your Answer")
    
    # Text input
    user_answer = st.text_area(
        "Type your answer",
        key=f"answer_input_{st.session_state.follow_up_count}",
        placeholder="Explain your understanding...",
        label_visibility="collapsed",
    )
    
    # Voice input
    audio_input = st.audio_input(
        "Or speak your answer",
        key=f"audio_input_{st.session_state.follow_up_count}",
    )
    
    if audio_input:
        with st.spinner("Transcribing..."):
            try:
                transcribed = ai.transcribe_audio(
                    st.session_state.openai_key,
                    audio_input.getvalue(),
                    "audio.webm",
                )
                st.success(f"Transcribed: {transcribed}")
                user_answer = transcribed
            except Exception as e:
                st.error(f"Transcription error: {e}")
    
    # Submit button
    col1, col2 = st.columns([3, 1])
    with col1:
        submit = st.button("Submit Answer", type="primary", use_container_width=True, disabled=not user_answer)
    with col2:
        skip = st.button("Skip", use_container_width=True)
    
    if skip:
        # Move to next card
        st.session_state.current_card_index += 1
        st.session_state.rephrased_question = ""
        st.session_state.review_state = "question"
        st.session_state.pop("played_question", None)
        st.session_state.pop("played_follow_up", None)
        
        if st.session_state.current_card_index >= len(st.session_state.current_cards):
            st.session_state.review_state = "complete"
        st.rerun()
    
    if submit and user_answer:
        with st.spinner("Evaluating your answer..."):
            # Determine what question we're evaluating against
            if st.session_state.review_state == "follow_up" and st.session_state.current_evaluation:
                current_question = st.session_state.current_evaluation.get("follow_up", st.session_state.rephrased_question)
            else:
                current_question = st.session_state.rephrased_question
            
            evaluation = ai.evaluate_answer(
                st.session_state.openai_key,
                current_question,
                st.session_state.original_answer,
                user_answer,
                st.session_state.conversation_history if st.session_state.conversation_history else None,
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
    
    if st.session_state.voice_mode:
        play_audio(feedback)
    
    # Show original answer for reference
    with st.expander("📖 Expected Answer"):
        st.write(st.session_state.original_answer)
    
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
    
    col1, col2, col3 = st.columns(3)
    
    # If there's a follow-up and we haven't hit the limit
    if follow_up and not is_correct and st.session_state.follow_up_count < max_follow_ups:
        with col1:
            if st.button("Continue Discussion", type="primary", use_container_width=True):
                st.session_state.follow_up_count += 1
                st.session_state.review_state = "follow_up"
                st.session_state.pop("played_follow_up", None)
                st.rerun()
    
    with col2:
        if st.button("Save & Next Card", use_container_width=True):
            # Save rephrased card to Feynman subdeck
            with st.spinner("Saving to Feynman deck..."):
                try:
                    card = st.session_state.current_cards[st.session_state.current_card_index]
                    deck_id = card.get("deck-id")
                    
                    # Get or create Feynman subdeck
                    feynman_deck_id = run_async(
                        mochi.get_or_create_feynman_subdeck(
                            st.session_state.mochi_key,
                            deck_id,
                            st.session_state.decks,
                        )
                    )
                    
                    # Build card content
                    card_content = ai.build_feynman_card_content(
                        st.session_state.original_question,
                        st.session_state.original_answer,
                        st.session_state.rephrased_question,
                        card.get("id", "unknown"),
                    )
                    
                    # Create the card
                    run_async(mochi.create_card(
                        st.session_state.mochi_key,
                        feynman_deck_id,
                        card_content,
                        tags=["feynman", "rephrased"],
                    ))
                    
                    st.success("Card saved to Feynman deck!")
                except Exception as e:
                    st.error(f"Failed to save: {e}")
            
            # Move to next card
            st.session_state.current_card_index += 1
            st.session_state.rephrased_question = ""
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.follow_up_count = 0
            st.session_state.pop("played_question", None)
            
            if st.session_state.current_card_index >= len(st.session_state.current_cards):
                st.session_state.review_state = "complete"
            st.rerun()
    
    with col3:
        if st.button("Skip (Don't Save)", use_container_width=True):
            st.session_state.current_card_index += 1
            st.session_state.rephrased_question = ""
            st.session_state.review_state = "question"
            st.session_state.conversation_history = []
            st.session_state.follow_up_count = 0
            st.session_state.pop("played_question", None)
            
            if st.session_state.current_card_index >= len(st.session_state.current_cards):
                st.session_state.review_state = "complete"
            st.rerun()


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
        st.rerun()
