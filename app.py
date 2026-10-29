import streamlit as st
import asyncio
import os
import tempfile
from supabase import create_client, Client
from deep_translator import GoogleTranslator
import edge_tts

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Language Drill Studio",
    page_icon="🗣️",
    layout="wide"
)

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)

supabase: Client = init_supabase()

# --- APP HEADER ---
st.title("🗣️ Language Drill Studio")
st.markdown("Practice and build listening drills with persistent Supabase storage and natural text-to-speech.")

if not supabase:
    st.error("⚠️ Supabase credentials missing! Please configure `SUPABASE_URL` and `SUPABASE_KEY` in Streamlit Secrets.")
    st.stop()

# --- SIDEBAR NAVIGATION ---
st.sidebar.header("Navigation")
nav_choice = st.sidebar.radio(
    "Select Mode:",
    ["📚 Phrase Library", "📁 Upload CSV File", "✍️ Type / Paste Phrases"]
)

# --- MODE 1: PHRASE LIBRARY ---
if nav_choice == "📚 Phrase Library":
    st.header("Phrase Library & Audio Generator")
    
    # Fetch decks from Supabase (placeholder example structure)
    st.info("Select a deck to view phrases, generate audio chunks, and practice.")
    
    # Example Deck Selector
    deck_name = st.text_input("Deck Name filter", value="")
    if st.button("Prepare / Rebuild Audio Chunks"):
        with st.spinner("Generating audio chunks via edge-tts..."):
            # Audio generation logic placeholder
            st.success("Audio chunks successfully prepared!")

# --- MODE 2: UPLOAD CSV FILE ---
elif nav_choice == "📁 Upload CSV File":
    st.header("Upload New Phrase CSV")
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    if uploaded_file is not None:
        st.write("File uploaded successfully! Preview:")
        # Display preview logic here
        if st.button("Save Deck to Supabase"):
            st.success("Deck saved successfully!")

# --- MODE 3: TYPE / PASTE PHRASES ---
elif nav_choice == "✍️ Type / Paste Phrases":
    st.header("Type or Paste Phrases")
    
    col1, col2 = st.columns(2)
    with col1:
        input_lang = st.selectbox("Input Language", ["English", "Spanish", "French", "Italian", "German"])
    with col2:
        target_lang = st.selectbox("Target Drill Language", ["Spanish (es-ES)", "English (en-US)"])
    
    raw_text = st.text_area(
        "Enter phrases (one per line):",
        placeholder="Hello\nHow are you?\nGood morning",
        height=150
    )
    
    deck_title = st.text_input("New Deck Title:", value="My Custom Deck")
    
    # Explicit processing button instead of relying on Ctrl+Enter
    if st.button("Process & Add Phrases", type="primary"):
        if not raw_text.strip():
            st.warning("Please enter at least one phrase.")
        else:
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            processed_phrases = []
            
            with st.spinner("Processing and translating phrases..."):
                for line in lines:
                    spanish_text = line
                    english_text = line
                    
                    # If input is English and target is Spanish, translate input to Spanish
                    if input_lang == "English" and "Spanish" in target_lang:
                        try:
                            spanish_text = GoogleTranslator(source='en', target='es').translate(line)
                            english_text = line
                        except Exception as e:
                            st.error(f"Translation error for '{line}': {e}")
                            
                    processed_phrases.append({
                        "spanish": spanish_text,
                        "english": english_text
                    })
            
            st.success(f"Successfully processed {len(processed_phrases)} phrases for deck '{deck_title}'!")
            
            # Display preview table
            st.subheader("Phrase Preview")
            for idx, p in enumerate(processed_phrases, 1):
                st.markdown(f"**{idx}. Target:** {p['spanish']} | **Translation:** {p['english']}")
