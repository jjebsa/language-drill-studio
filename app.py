import streamlit as st
import asyncio
import os
import tempfile
import time
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

# --- HELPER: AUDIO GENERATION ---
async def generate_audio_async(text, voice, rate_str, output_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    await communicate.save(output_path)

def get_audio_bytes(text, voice="es-ES-AlvaroNeural", rate_str="+0%"):
    if not text:
        return None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tf:
        tmp_path = tf.name
    try:
        loop.run_until_complete(generate_audio_async(text, voice, rate_str, tmp_path))
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        return audio_bytes
    except Exception as e:
        st.error(f"Audio generation error: {e}")
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# --- TOP-LEVEL TABS ---
tab_practice, tab_upload, tab_paste = st.tabs([
    "📚 Practice Studio & Library",
    "📁 Upload CSV / TSV File",
    "✍️ Type / Paste Phrases"
])


# ==========================================
# TAB 1: PRACTICE STUDIO & LIBRARY
# ==========================================
with tab_practice:
    st.header("Listening Drill Studio")
    
    # Reload deck list from Supabase
    try:
        decks_res = supabase.table("decks").select("name").execute()
        deck_names = [d["name"] for d in decks_res.data] if decks_res.data else []
    except Exception as e:
        deck_names = []
        st.warning(f"Could not load decks from Supabase: {e}")

    if not deck_names:
        st.info("No decks found in Supabase yet. Use the 'Upload CSV / TSV File' or 'Type / Paste Phrases' tabs above to add your first deck!")
    else:
        col_deck_sel, col_deck_del = st.columns([3, 1])
        with col_deck_sel:
            selected_deck = st.selectbox("Select Drill Deck:", deck_names, key="active_deck_select")
        with col_deck_del:
            st.write("") # Alignment spacing
            st.write("") 
            if st.button("🗑️ Delete Selected Deck", type="secondary"):
                if selected_deck:
                    try:
                        supabase.table("decks").delete().eq("name", selected_deck).execute()
                        st.success(f"Deleted deck '{selected_deck}'!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting deck: {e}")

        if selected_deck:
            try:
                phrases_res = supabase.table("phrases").select("*").eq("deck_name", selected_deck).execute()
                phrases_data = phrases_res.data if phrases_res.data else []
            except Exception as e:
                phrases_data = []
                st.error(f"Error loading phrases for deck '{selected_deck}': {e}")
            
            st.markdown(f"**Loaded Deck:** `{selected_deck}` ({len(phrases_data)} phrases available)")
            st.divider()
            
            # Practice Settings
            st.subheader("⚙️ Practice Settings")
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                speed_choice = st.selectbox(
                    "Speech Speed",
                    ["Normal (0%)", "Slower (-15%)", "Slow (-30%)", "Faster (+15%)"],
                    index=0
                )
                rate_mapping = {
                    "Normal (0%)": "+0%",
                    "Slower (-15%)": "-15%",
                    "Slow (-30%)": "-30%",
                    "Faster (+15%)": "+15%"
                }
                selected_rate = rate_mapping[speed_choice]
                
            with c2:
                repetitions = st.number_input("Repetitions per phrase", min_value=1, max_value=5, value=2)
                
            with c3:
                pause_duration = st.slider("Pause between phrases (s)", 0.0, 5.0, 1.5, 0.5)
                
            with c4:
                show_translation = st.checkbox("Show English Translations", value=True)
            
            st.divider()
            
            # Global Drill Controls
            st.subheader("🎧 Global Drill Player")
            
            col_p1, col_p2 = st.columns([2, 2])
            with col_p1:
                start_drill = st.button("▶️ Start Full Sequential Drill", type="primary", use_container_width=True)
            with col_p2:
                stop_drill = st.button("⏹️ Stop Drill", type="secondary", use_container_width=True)

            # Continuous Drill Execution Loop
            if start_drill:
                drill_placeholder = st.empty()
                audio_placeholder = st.empty()
                
                for idx, p in enumerate(phrases_data, 1):
                    target = p.get("spanish", "")
                    translation = p.get("english", "")
                    
                    # Highlight active phrase in UI
                    display_text = f"### 🔊 Playing [{idx}/{len(phrases_data)}]: **{target}**"
                    if show_translation:
                        display_text += f"\n*Translation: {translation}*"
                    drill_placeholder.markdown(display_text)
                    
                    # Fetch audio for target phrase
                    audio_bytes = get_audio_bytes(target, rate_str=selected_rate)
                    
                    # Repeat $N$ times with configured pauses
                    if audio_bytes:
                        for rep in range(repetitions):
                            audio_placeholder.audio(audio_bytes, format="audio/mp3", autoplay=True)
                            time.sleep(1.2) # Wait for audio playback duration estimate
                            if pause_duration > 0 and rep < repetitions - 1:
                                time.sleep(pause_duration)
                    
                    # Pause between distinct phrases
                    if pause_duration > 0:
                        time.sleep(pause_duration)
                
                drill_placeholder.success("🎉 Drill completed!")

            st.divider()
            
            # Phrase List Preview
            st.subheader("Phrase List")
            for idx, p in enumerate(phrases_data, 1):
                target = p.get("spanish", "")
                translation = p.get("english", "")
                
                row_cols = st.columns([3, 1])
                with row_cols[0]:
                    if show_translation:
                        st.markdown(f"**{idx}.** {target} &nbsp;|&nbsp; *{translation}*")
                    else:
                        st.markdown(f"**{idx}.** {target}")
                with row_cols[1]:
                    if st.button("▶ Play", key=f"play_single_{idx}"):
                        audio_data = get_audio_bytes(target, rate_str=selected_rate)
                        if audio_data:
                            st.audio(audio_data, format="audio/mp3", autoplay=True)


# ==========================================
# TAB 2: UPLOAD CSV / TSV FILE
# ==========================================
with tab_upload:
    st.header("Upload Bilingual Phrase File")
    uploaded_file = st.file_uploader("Choose a CSV or TSV file", type=["csv", "tsv", "txt"])
    deck_title_input = st.text_input("New Deck Name:", value="Imported Deck")
    
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.tsv') or uploaded_file.name.endswith('.txt'):
                df = pd.read_csv(uploaded_file, sep='\t')
            else:
                df = pd.read_csv(uploaded_file)
                
            st.write("File preview (first 5 rows):")
            st.dataframe(df.head())
            
            if st.button("Save Deck to Supabase", type="primary"):
                with st.spinner("Saving deck to Supabase..."):
                    supabase.table("decks").upsert({"name": deck_title_input}).execute()
                    
                    cols = {c.lower(): c for c in df.columns}
                    col_es = cols.get('spanish', df.columns[0] if len(df.columns) > 0 else None)
                    col_en = cols.get('english', df.columns[1] if len(df.columns) > 1 else col_es)
                    
                    success_count = 0
                    for _, row in df.iterrows():
                        spanish_val = str(row[col_es]) if col_es else ""
                        english_val = str(row[col_en]) if col_en else ""
                        supabase.table("phrases").insert({
                            "deck_name": deck_title_input,
                            "spanish": spanish_val,
                            "english": english_val
                        }).execute()
                        success_count += 1
                    
                    st.success(f"Successfully saved deck '{deck_title_input}' with {success_count} phrases!")
                    st.rerun()
        except Exception as e:
            st.error(f"Error parsing file: {e}")


# ==========================================
# TAB 3: TYPE / PASTE PHRASES
# ==========================================
with tab_paste:
    st.header("Type or Paste Bilingual Phrases")
    raw_text = st.text_area(
        "Phrase pairs (format: Spanish | English):",
        placeholder="Hola | Hello\n¿Cómo estás? | How are you?\nBuenos días | Good morning",
        height=150
    )
    
    deck_title = st.text_input("Deck Title:", value="Custom Deck")
    separator_choice = st.selectbox("Delimiter separator used:", ["| (Pipe)", ", (Comma)", "\\t (Tab)"])
    
    if st.button("Process & Save Deck", type="primary"):
        if not raw_text.strip():
            st.warning("Please enter at least one phrase pair.")
        else:
            sep = "|" if "|" in separator_choice else ("," if "," in separator_choice else "\t")
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            
            supabase.table("decks").upsert({"name": deck_title}).execute()
            
            for line in lines:
                if sep in line:
                    parts = line.split(sep, 1)
                    spanish_text = parts[0].strip()
                    english_text = parts[1].strip()
                else:
                    spanish_text = line
                    english_text = line
                
                supabase.table("phrases").insert({
                    "deck_name": deck_title,
                    "spanish": spanish_text,
                    "english": english_text
                }).execute()
            
            st.success(f"Successfully saved deck '{deck_title}'! Refreshing...")
            st.rerun()
