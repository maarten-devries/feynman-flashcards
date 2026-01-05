"""
Mochi Cards API Client

Provides functions to interact with the Mochi flashcards API.
All functions accept an API key as parameter (never from env) for security.
"""

import httpx
import re
from base64 import b64encode
from typing import Optional


BASE_URL = "https://app.mochi.cards/api"


def _get_auth_header(api_key: str) -> dict:
    """Create Basic Auth header from API key."""
    encoded = b64encode(f"{api_key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _get_headers(api_key: str) -> dict:
    """Get full headers for API requests."""
    return {
        **_get_auth_header(api_key),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Validate a Mochi API key by attempting to fetch decks.
    
    Returns:
        (success, message) tuple
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/decks",
                headers=_get_headers(api_key),
                timeout=10.0,
            )
            if response.status_code == 200:
                return True, "Connected to Mochi"
            elif response.status_code == 401:
                return False, "Invalid API key"
            else:
                return False, f"Error: {response.status_code}"
    except httpx.TimeoutException:
        return False, "Connection timed out"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


async def get_decks(api_key: str) -> list[dict]:
    """
    Fetch all decks from Mochi.
    
    Returns:
        List of deck objects with id, name, parent-id, etc.
    """
    decks = []
    bookmark = None
    
    async with httpx.AsyncClient() as client:
        while True:
            url = f"{BASE_URL}/decks"
            if bookmark:
                url += f"?bookmark={bookmark}"
            
            response = await client.get(
                url,
                headers=_get_headers(api_key),
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            
            decks.extend(data.get("docs", []))
            
            new_bookmark = data.get("bookmark")
            if not new_bookmark or new_bookmark == bookmark:
                break
            bookmark = new_bookmark
    
    return decks


async def get_due_cards(api_key: str, deck_id: Optional[str] = None) -> list[dict]:
    """
    Fetch cards due for review.
    
    Args:
        api_key: Mochi API key
        deck_id: Optional deck ID to filter by
        
    Returns:
        List of card objects with content, reviews, etc.
    """
    async with httpx.AsyncClient() as client:
        if deck_id:
            url = f"{BASE_URL}/due/{deck_id}"
        else:
            url = f"{BASE_URL}/due"
        
        response = await client.get(
            url,
            headers=_get_headers(api_key),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("cards", [])


async def get_cards_by_deck(api_key: str, deck_id: str) -> list[dict]:
    """
    Fetch all cards from a specific deck.
    
    Args:
        api_key: Mochi API key
        deck_id: Deck ID to fetch cards from
        
    Returns:
        List of all card objects in the deck
    """
    cards = []
    bookmark = None
    
    async with httpx.AsyncClient() as client:
        while True:
            url = f"{BASE_URL}/cards?deck-id={deck_id}&limit=100"
            if bookmark:
                url += f"&bookmark={bookmark}"
            
            response = await client.get(
                url,
                headers=_get_headers(api_key),
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            
            cards.extend(data.get("docs", []))
            
            new_bookmark = data.get("bookmark")
            if not new_bookmark or new_bookmark == bookmark or not data.get("docs"):
                break
            bookmark = new_bookmark
    
    return cards


async def get_card(api_key: str, card_id: str) -> dict:
    """
    Fetch a single card by ID.
    
    Returns:
        Card object
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/cards/{card_id}",
            headers=_get_headers(api_key),
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


async def create_card(
    api_key: str,
    deck_id: str,
    content: str,
    tags: Optional[list[str]] = None,
) -> dict:
    """
    Create a new card in the specified deck.
    
    Args:
        api_key: Mochi API key
        deck_id: Target deck ID
        content: Markdown content for the card
        tags: Optional list of tags (without # prefix)
        
    Returns:
        Created card object
    """
    payload = {
        "content": content,
        "deck-id": deck_id,
    }
    
    if tags:
        payload["manual-tags"] = tags
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/cards",
            headers=_get_headers(api_key),
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


async def update_card_content(
    api_key: str,
    card_id: str,
    content: str,
) -> dict:
    """
    Update a card's content.
    
    Args:
        api_key: Mochi API key
        card_id: Card ID to update
        content: New markdown content
        
    Returns:
        Updated card object
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/cards/{card_id}",
            headers=_get_headers(api_key),
            json={"content": content},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


def build_deck_tree(decks: list[dict]) -> dict:
    """
    Build a tree structure from flat deck list for display.
    
    Returns:
        Dict mapping deck_id -> deck info with children
    """
    tree = {}
    for deck in decks:
        deck_id = deck["id"]
        tree[deck_id] = {
            **deck,
            "children": [],
        }
    
    # Link children to parents
    for deck in decks:
        parent_id = deck.get("parent-id")
        if parent_id and parent_id in tree:
            tree[parent_id]["children"].append(deck["id"])
    
    return tree


def get_deck_display_name(deck: dict, tree: dict, max_depth: int = 3) -> str:
    """
    Get a display name for a deck showing its hierarchy.
    
    Example: "Parent / Child / Grandchild"
    """
    parts = [deck.get("name", "Unnamed")]
    current = deck
    depth = 0
    
    while current.get("parent-id") and depth < max_depth:
        parent_id = current["parent-id"]
        if parent_id in tree:
            parent = tree[parent_id]
            parts.insert(0, parent.get("name", "Unnamed"))
            current = parent
            depth += 1
        else:
            break
    
    return " / ".join(parts)


async def get_attachment(api_key: str, card_id: str, filename: str) -> tuple[bytes, str]:
    """
    Fetch an attachment from a card.
    
    Args:
        api_key: Mochi API key
        card_id: Card ID
        filename: Attachment filename
        
    Returns:
        Tuple of (bytes, content_type)
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/cards/{card_id}/attachments/{filename}",
            headers=_get_auth_header(api_key),
            timeout=30.0,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png")
        return response.content, content_type


async def resolve_card_images(api_key: str, card_id: str, content: str) -> str:
    """
    Replace @media/ references in card content with base64 data URLs.
    
    Args:
        api_key: Mochi API key
        card_id: Card ID (for fetching attachments)
        content: Card markdown content
        
    Returns:
        Content with images converted to base64 data URLs
    """
    # Find all @media references: ![](@media/filename) or ![alt](@media/filename)
    pattern = r'!\[([^\]]*)\]\(@media/([^)]+)\)'
    matches = re.findall(pattern, content)
    
    if not matches:
        return content
    
    resolved_content = content
    
    for alt_text, filename in matches:
        try:
            image_bytes, content_type = await get_attachment(api_key, card_id, filename)
            # Convert to base64 data URL
            b64_data = b64encode(image_bytes).decode()
            data_url = f"data:{content_type};base64,{b64_data}"
            # Replace in content
            old_ref = f"![](@media/{filename})" if not alt_text else f"![{alt_text}](@media/{filename})"
            new_ref = f"![]({data_url})" if not alt_text else f"![{alt_text}]({data_url})"
            resolved_content = resolved_content.replace(old_ref, new_ref)
        except Exception as e:
            # If we can't fetch the image, leave the reference as-is
            print(f"Failed to fetch attachment {filename}: {e}")
            continue
    
    return resolved_content
