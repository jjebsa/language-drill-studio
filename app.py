import streamlit as st
import asyncio
import os
import tempfile
import pandas as pd
from supabase import create_client, Client
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
    ["📚 Phrase Library", "📁 Upload CSV / TSV File", "✍️ Type / Paste Bilingual Phrases"]
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
        st.info("No decks found in Supabase yet. Use 'Upload CSV / TSV File' or 'Type / Paste Bilingual Phrases' to add your first deck!")
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
                        spanish_text = item.get("spanish")
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
                target = p.get("spanish", "")
                translation = p.get("english", "")
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**{idx}.** {target} *(Translation: {translation})*")
                with col_b:
                    if st.button("Play Audio", key=f"play_{idx}"):
                        audio_data = get_audio_bytes(target)
                        if audio_data:
                            st.audio(audio_data, format="audio/mp3")


# --- MODE 2: UPLOAD CSV / TSV FILE ---
elif nav_choice == "📁 Upload CSV / TSV File":
    st.header("Upload Bilingual Phrase File")
    uploaded_file = st.file_uploader("Choose a CSV or TSV file (Columns: spanish, english)", type=["csv", "tsv", "txt"])
    deck_title_input = st.text_input("Deck Name:", value="My Imported Deck")
    
    if uploaded_file is not None:
        try:
            # Auto-detect separator based on file extension
            if uploaded_file.name.endswith('.tsv') or uploaded_file.name.endswith('.txt'):
                df = pd.read_csv(uploaded_file, sep='\t')
            else:
                df = pd.read_csv(uploaded_file)
                
            st.write("File uploaded successfully! Preview (first 5 rows):")
            st.dataframe(df.head())
            
            if st.button("Save Deck to Supabase", type="primary"):
                with st.spinner("Saving deck to Supabase..."):
                    try:
                        supabase.table("decks").upsert({"name": deck_title_input}).execute()
                    except Exception as e:
                        st.warning(f"Deck upsert notice: {e}")
                    
                    success_count = 0
                    # Expecting columns like 'spanish' and 'english' (case-insensitive search)
                    cols = {c.lower(): c for c in df.columns}
                    col_es = cols.get('spanish', df.columns[0] if len(df.columns) > 0 else None)
                    col_en = cols.get('english', df.columns[1] if len(df.columns) > 1 else col_es)
                    
                    for _, row in df.iterrows():
                        spanish_val = str(row[col_es]) if col_es else ""
                        english_val = str(row[col_en]) if col_en else ""
                        try:
                            supabase.table("phrases").insert({
                                "deck_name": deck_title_input,
                                "spanish": spanish_val,
                                "english": english_val
                            }).execute()
                            success_count += 1
                        except Exception:
                            pass
                    st.success(f"Successfully saved deck '{deck_title_input}' with {success_count} phrases to Supabase!")
        except Exception as e:
            st.error(f"Error parsing file: {e}")


# --- MODE 3: TYPE / PASTE BILINGUAL PHRASES ---
elif nav_choice == "✍️ Type / Paste Bilingual Phrases":
    st.header("Type or Paste Bilingual Phrases")
    st.markdown("Enter phrases with Spanish and English separated by a tab or comma (e.g. `Hola,Hello` or `Buenos días	Good morning`).")
    
    raw_text = st.text_area(
        "Enter phrases (format: Spanish | English per line):",
        placeholder="Hola | Hello\n¿Cómo estás? | How are you?\nBuenos días | Good morning",
        height=150
    )
    
    deck_title = st.text_input("New Deck Title:", value="My Custom Deck")
    separator_choice = st.selectbox("Delimiter separator used:", ["| (Pipe)", ", (Comma)", "\\t (Tab)"])
    
    if st.button("Process & Save Deck", type="primary"):
        if not raw_text.strip():
            st.warning("Please enter at least one phrase pair.")
        else:
            sep = "|" if "|" in separator_choice else ("," if "," in separator_choice else "\t")
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            processed_phrases = []
            
            for line in lines:
                if sep in line:
                    parts = line.split(sep, 1)
                    spanish_text = parts[0].strip()
                    english_text = parts[1].strip()
                else:
                    spanish_text = line
                    english_text = line
                
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
                st.markdown(f"**{idx}. Spanish:** {p['spanish']} | **English:** {p['english']}")
