import streamlit as st
import asyncio
import os
import tempfile
import pandas as pd
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

# --- HELPER: AUDIO GENERATION ---
async def generate_audio_async(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def get_audio_bytes(text, voice="es-ES-AlvaroNeural"):
    if not text:
        return None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
        tmp_path = tf.name
    try:
        loop.run_until_complete(generate_audio_async(text, voice, tmp_path))
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        return audio_bytes
    except Exception as e:
        st.error(f"Audio generation error: {e}")
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# --- MODE 1: PHRASE LIBRARY ---
if nav_choice == "📚 Phrase Library":
    st.header("Phrase Library & Audio Generator")
    
    try:
        decks_res = supabase.table("decks").select("name").execute()
        deck_names = [d["name"] for d in decks_res.data] if decks_res.data else []
    except Exception as e:
        deck_names = []
        st.sidebar.warning(f"Could not load decks from Supabase: {e}")

    if not deck_names:
        st.info("No decks found in Supabase yet. Use 'Upload CSV File' or 'Type / Paste Phrases' to add your first deck!")
    else:
        selected_deck = st.selectbox("Select Deck", deck_names)
        if selected_deck:
            try:
                phrases_res = supabase.table("phrases").select("*").eq("deck_name", selected_deck).execute()
                phrases_data = phrases_res.data if phrases_res.data else []
            except Exception as e:
                phrases_data = []
                st.error(f"Error loading phrases for deck '{selected_deck}': {e}")
            
            st.subheader(f"Deck: {selected_deck} ({len(phrases_data)} phrases)")
            
            if st.button("Prepare / Rebuild Audio Chunks"):
                with st.spinner("Generating audio chunks via edge-tts..."):
                    for item in phrases_data:
                        spanish_text = item.get("spanish") or item.get("target_text")
                        if spanish_text:
                            audio_bytes = get_audio_bytes(spanish_text)
                            if audio_bytes and supabase:
                                try:
                                    file_path = f"{selected_deck}/{hash(spanish_text)}.mp3"
                                    supabase.storage.from_("audio-cache").upload(
                                        file_path, audio_bytes, file_options={"upsert": "true"}
                                    )
                                except Exception:
                                    pass
                    st.success("Audio chunks successfully prepared and cached!")
            
            for idx, p in enumerate(phrases_data, 1):
                target = p.get("spanish") or p.get("target_text", "")
                translation = p.get("english") or p.get("translation_text", "")
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**{idx}.** {target} *(Translation: {translation})*")
                with col_b:
                    if st.button("Play Audio", key=f"play_{idx}"):
                        audio_data = get_audio_bytes(target)
                        if audio_data:
                            st.audio(audio_data, format="audio/mp3")


# --- MODE 2: UPLOAD CSV FILE ---
elif nav_choice == "📁 Upload CSV File":
    st.header("Upload New Phrase CSV")
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    deck_title_input = st.text_input("Deck Name for CSV:", value="Uploaded Deck")
    
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.write("File uploaded successfully! Preview (first 5 rows):")
            st.dataframe(df.head())
            
            if st.button("Save Deck to Supabase", type="primary"):
                with st.spinner("Saving deck to Supabase..."):
                    try:
                        supabase.table("decks").upsert({"name": deck_title_input}).execute()
                    except Exception:
                        pass
                    
                    success_count = 0
                    for _, row in df.iterrows():
                        target_val = str(row.iloc[0]) if len(row) > 0 else ""
                        trans_val = str(row.iloc[1]) if len(row) > 1 else target_val
                        try:
                            supabase.table("phrases").insert({
                                "deck_name": deck_title_input,
                                "spanish": target_val,
                                "english": trans_val
                            }).execute()
                            success_count += 1
                        except Exception:
                            pass
                    st.success(f"Successfully saved deck '{deck_title_input}' with {success_count} phrases to Supabase!")
        except Exception as e:
            st.error(f"Error parsing CSV file: {e}")


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
    
    if st.button("Process & Add Phrases", type="primary"):
        if not raw_text.strip():
            st.warning("Please enter at least one phrase.")
        else:
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            processed_phrases = []
            
            with st.spinner("Processing and translating phrases (batch mode)..."):
                translated_lines = lines
                if input_lang == "English" and "Spanish" in target_lang:
                    try:
                        translator = GoogleTranslator(source='en', target='es')
                        translated_lines = translator.translate_batch(lines)
                    except Exception as e:
                        st.warning(f"Batch translation warning: {e}. Using raw text.")
                        translated_lines = lines

                for orig, trans in zip(lines, translated_lines):
                    spanish_text = trans if "Spanish" in target_lang else orig
                    english_text = orig if input_lang == "English" else trans
                    processed_phrases.append({
                        "spanish": spanish_text,
                        "english": english_text
                    })
            
            try:
                supabase.table("decks").upsert({"name": deck_title}).execute()
                for p in processed_phrases:
                    supabase.table("phrases").insert({
                        "deck_name": deck_title,
                        "spanish": p["spanish"],
                        "english": p["english"]
                    }).execute()
                st.success(f"Successfully saved deck '{deck_title}' with {len(processed_phrases)} phrases to Supabase!")
            except Exception as e:
                st.warning(f"Processed successfully, but Supabase storage notice: {e}")
            
            st.subheader("Phrase Preview")
            for idx, p in enumerate(processed_phrases, 1):
                st.markdown(f"**{idx}. Target:** {p['spanish']} | **Translation:** {p['english']}")
