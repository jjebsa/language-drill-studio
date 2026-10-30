import streamlit as st
import asyncio
import os
import tempfile
import time
import base64
import pandas as pd
from supabase import create_client, Client
import edge_tts

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Language Practice Studio",
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
st.title("🗣️ Language Practice Studio")
st.markdown("Practice speaking and listening skills.")

if not supabase:
    st.error("⚠️ Supabase credentials missing! Please configure `SUPABASE_URL` and `SUPABASE_KEY` in Streamlit Secrets.")
    st.stop()

# --- HELPER: AUDIO GENERATION & SILENT PLAYBACK ---
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

def play_audio_silently(audio_bytes):
    """Injects base64 encoded audio into HTML to play automatically without any visible player UI."""
    if not audio_bytes:
        return
    b64 = base64.b64encode(audio_bytes).decode()
    audio_html = f'<audio autoplay="true" src="data:audio/mp3;base64,{b64}"></audio>'
    st.markdown(audio_html, unsafe_allow_html=True)


# --- INITIALIZE SESSION STATE FOR DRILL RUNNER ---
if "drill_active" not in st.session_state:
    st.session_state["drill_active"] = False
if "drill_paused" not in st.session_state:
    st.session_state["drill_paused"] = False
if "current_phrase_idx" not in st.session_state:
    st.session_state["current_phrase_idx"] = 0


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
    st.header("Speaking and Listening Studio")
    
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
            selected_deck = st.selectbox("Select Practice Deck:", deck_names, key="active_deck_select")
        with col_deck_del:
            st.write("") 
            st.write("") 
            if st.button("🗑️ Delete Deck", type="secondary"):
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
            
            # --- EDIT DECK & PHRASES EXPANDER ---
            with st.expander("✏️ Edit Deck Name & Phrases"):
                new_deck_name = st.text_input("Rename Deck", value=selected_deck, key="rename_deck_input")
                if st.button("Update Deck Name"):
                    if new_deck_name and new_deck_name != selected_deck:
                        try:
                            supabase.table("decks").update({"name": new_deck_name}).eq("name", selected_deck).execute()
                            supabase.table("phrases").update({"deck_name": new_deck_name}).eq("deck_name", selected_deck).execute()
                            st.success("Deck renamed successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error renaming deck: {e}")
                
                st.markdown("### Modify Phrases")
                df_phrases = pd.DataFrame(phrases_data)
                if not df_phrases.empty:
                    editable_df = df_phrases[['spanish', 'english']] if 'spanish' in df_phrases.columns else df_phrases
                    edited_df = st.data_editor(editable_df, num_rows="dynamic", key=f"editor_{selected_deck}")
                    
                    if st.button("Save Phrase Changes", type="primary"):
                        try:
                            supabase.table("phrases").delete().eq("deck_name", selected_deck).execute()
                            for _, row in edited_df.iterrows():
                                es = str(row.get("spanish", "")).strip()
                                en = str(row.get("english", "")).strip()
                                if es:
                                    supabase.table("phrases").insert({
                                        "deck_name": selected_deck,
                                        "spanish": es,
                                        "english": en
                                    }).execute()
                            st.success("Phrases updated successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating phrases: {e}")

            st.divider()
            
            # Practice Settings
            st.subheader("⚙️ Practice Settings")
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                speed_choice = st.selectbox(
                    "Speech Speed",
                    ["Normal (0%)", "Slower (-15%)", "Slow (-30%)", "Faster (+15%)"],
                    index=0,
                    key="setting_speed"
                )
                rate_mapping = {
                    "Normal (0%)": "+0%",
                    "Slower (-15%)": "-15%",
                    "Slow (-30%)": "-30%",
                    "Faster (+15%)": "+15%"
                }
                selected_rate = rate_mapping[speed_choice]
                
            with c2:
                repetitions = st.number_input("Repetitions per phrase", min_value=1, max_value=5, value=1, key="setting_reps")
                
            with c3:
                pause_duration = st.slider("Pause between phrases (s)", 0.0, 10.0, 2.0, 0.5, key="setting_pause")
                
            with c4:
                reverse_recall = st.checkbox("Reverse Recall (Show EN, play ES)", value=False, key="setting_reverse")
                show_translation = st.checkbox("Show Translations", value=True, key="setting_show_trans")
            
            st.divider()
            
            # Global Drill Controls
            st.subheader("🎧 List Player")
            
            col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
            with col_p1:
                if st.button("▶️ Start / Restart Drill", type="primary", use_container_width=True):
                    st.session_state["drill_active"] = True
                    st.session_state["drill_paused"] = False
                    st.session_state["current_phrase_idx"] = 0
                    st.rerun()
                    
            with col_p2:
                pause_label = "▶️ Resume Drill" if st.session_state["drill_paused"] else "⏸️ Pause Drill"
                if st.button(pause_label, use_container_width=True, disabled=not st.session_state["drill_active"]):
                    st.session_state["drill_paused"] = not st.session_state["drill_paused"]
                    st.rerun()
                    
            with col_p3:
                if st.button("⏹️ Stop Drill", type="secondary", use_container_width=True, disabled=not st.session_state["drill_active"]):
                    st.session_state["drill_active"] = False
                    st.session_state["drill_paused"] = False
                    st.session_state["current_phrase_idx"] = 0
                    st.rerun()

            # Active Stateful Drill Display
            if st.session_state["drill_active"] and phrases_data:
                curr_idx = st.session_state["current_phrase_idx"]
                
                if curr_idx < len(phrases_data):
                    p = phrases_data[curr_idx]
                    target = p.get("spanish", "")
                    translation = p.get("english", "")
                    
                    # Display Text Logic
                    if reverse_recall:
                        main_text = translation if translation else "(No translation)"
                        sub_text = target if show_translation else "🔊 [Recall and Say the Spanish]"
                    else:
                        main_text = target
                        sub_text = f"*{translation}*" if show_translation else ""
                    
                    # Render Dark Focus Card
                    border_color = "#ffc107" if st.session_state["drill_paused"] else "#ffffff"
                    status_badge = " <span style='color:#ffc107; font-size:1rem;'>(PAUSED)</span>" if st.session_state["drill_paused"] else ""
                    
                    st.markdown(f"""
                    <div style="background-color: #0e1117; color: #ffffff; padding: 40px; border-radius: 12px; text-align: center; border: 1px solid {border_color}; margin: 20px 0;">
                        <h2 style="color: #ffffff; font-size: 2.5rem; margin-bottom: 15px;">{main_text}{status_badge}</h2>
                        <h4 style="color: #adb5bd; font-weight: 400; margin: 0;">{sub_text}</h4>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Navigation Controls while drill is active
                    col_nav1, col_nav2 = st.columns([1, 1])
                    with col_nav1:
                        if st.button("⏮️ Previous Phrase", use_container_width=True) and curr_idx > 0:
                            st.session_state["current_phrase_idx"] -= 1
                            st.rerun()
                    with col_nav2:
                        if st.button("⏭️ Next Phrase", use_container_width=True) and curr_idx < len(phrases_data) - 1:
                            st.session_state["current_phrase_idx"] += 1
                            st.rerun()

                    # Audio Playback Loop (Only triggers when NOT paused)
                    if not st.session_state["drill_paused"]:
                        # Distribute pause duration cleanly for recall mode (60% thinking time before audio, 40% after)
                        thinking_time = (pause_duration * 0.6) if reverse_recall else 0
                        post_audio_pause = pause_duration - thinking_time if reverse_recall else pause_duration

                        if thinking_time > 0:
                            time.sleep(thinking_time)
                        
                        audio_bytes = get_audio_bytes(target, rate_str=selected_rate)
                        if audio_bytes:
                            for rep in range(repetitions):
                                play_audio_silently(audio_bytes)
                                time.sleep(1.2) # Snappy audio buffer
                                if post_audio_pause > 0 and rep < repetitions - 1:
                                    time.sleep(post_audio_pause)
                        
                        if post_audio_pause > 0:
                            time.sleep(post_audio_pause)
                        
                        # Automatically step to next phrase
                        if st.session_state["current_phrase_idx"] < len(phrases_data) - 1:
                            st.session_state["current_phrase_idx"] += 1
                            st.rerun()
                        else:
                            st.session_state["drill_active"] = False
                            st.success("🎉 Drill completed!")
                            st.rerun()
                else:
                    st.session_state["drill_active"] = False

            st.divider()
            
            # Phrase List Preview
            st.subheader("Phrase List")
            for idx, p in enumerate(phrases_data, 1):
                target = p.get("spanish", "")
                translation = p.get("english", "")
                
                row_cols = st.columns([3, 1])
                with row_cols[0]:
                    if reverse_recall:
                        display_str = f"**{idx}.** {translation} &nbsp;|&nbsp; *(Think of Spanish)*"
                    elif show_translation:
                        display_str = f"**{idx}.** {target} &nbsp;|&nbsp; *{translation}*"
                    else:
                        display_str = f"**{idx}.** {target}"
                    st.markdown(display_str)
                with row_cols[1]:
                    if st.button("▶ Play", key=f"play_single_{idx}"):
                        audio_data = get_audio_bytes(target, rate_str=selected_rate)
                        if audio_data:
                            play_audio_silently(audio_data)


# ==========================================
# TAB 2: UPLOAD CSV / TSV FILE
# ==========================================
with tab_upload:
    st.header("Upload Bilingual Phrase File")
    uploaded_file = st.file_uploader("Choose a CSV or TSV file", type=["csv", "tsv", "txt"])
    deck_title_input = st.text_input("New Deck Name:", placeholder="Imported Deck")
    
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
    
    deck_title = st.text_input("New Deck Title:", placeholder="(Add your new deck name here.)")
    separator_choice = st.selectbox("Select delimiter separator used:", ["| (Pipe)", ", (Comma)", "\\t (Tab)"])
    
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
