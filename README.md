# Feynman Flashcards 🧠

A Streamlit app that turns your [Mochi](https://mochi.cards) flashcards into Socratic review sessions. Instead of just flipping cards, an AI tutor rephrases questions and evaluates your understanding with follow-up questions.

## Features

- 🎯 AI rephrases flashcard questions to test deeper understanding
- 💬 Socratic evaluation with follow-up questions
- 🎤 Voice input for answers (always available)
- ✏️ Edit flashcard answers directly from the review screen
- 📚 Optional source context for richer feedback

## Setup

1. Clone and install dependencies:
   ```bash
   git clone https://github.com/maarten-devries/feynman-flashcards.git
   cd feynman-flashcards
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a `.env` file with your API keys:
   ```
   MOCHI_API_KEY=your_mochi_key
   ANTHROPIC_API_KEY=your_anthropic_key
   OPENAI_API_KEY=your_openai_key  # Optional, for voice features
   ```

3. Run the app:
   ```bash
   streamlit run app.py
   ```

## API Keys

- **Mochi**: [mochi.cards](https://mochi.cards) → Settings → API
- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/settings/keys)
- **OpenAI** (optional): [platform.openai.com](https://platform.openai.com/api-keys) - enables voice input/output

## License

MIT
