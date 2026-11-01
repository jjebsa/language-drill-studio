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

# --- CUSTOM COMPACT STYLING & SMALLER HEADINGS ---
st.markdown("""
<style>
    /* Reduce top padding of main container */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }
    /* Compact Headings */
    h1 { font-size: 1.8rem !important; margin-bottom: 0.5rem !important; }
    h2 { font-size: 1.4rem !important; margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
    h3 { font-size: 1.1rem !important; margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
    
    /* Smaller Tab Titles */
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem !important;
        padding-top: 4px !important;
        padding-bottom: 4px !important;
    }
    /* Reduce divider spacing */
    hr { margin: 1rem 0 !important; }
</style>
""", unsafe_allow_html=True)

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
st.caption("Practice speaking and listening skills, or manage your bilingual phrase decks.")

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

def inject_drill_helpers(is_active):
    """Injects JS to keep the mobile screen awake during active drills."""
    if is_active:
        wake_lock_js = """
        <script>
        let wakeLock = null;
        async function requestWakeLock() {
            try {
                if ('wakeLock' in navigator) {
                    wakeLock = await navigator.wakeLock.request('screen');
                }
            } catch (err) {
                console.log(err);
            }
        }
        requestWakeLock();
        </script>
        """
        st.markdown(wake_lock_js, unsafe_allow_html=True)
    else:
        release_js = """
        <script>
        if (typeof wakeLock !== 'undefined' && wakeLock !== null) {
            wakeLock.release().then(() => { wakeLock = null; });
        }
        </script>
        """
        st.markdown(release_js, unsafe_allow_html=True)

# --- DIALOG: DELETE CONFIRMATION ---
@st.dialog("Confirm Deck Deletion")
def confirm_delete_dialog(deck_name):
    st.write(f"Are you sure you want to delete the selected deck **'{deck_name}'**?")
    st.caption("This action will permanently delete all associated phrases.")
    c_cancel, c_confirm = st.columns(2)
    with c_cancel:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with c_confirm:
        if st.button("Confirm Delete", type="primary", use_container_width=True):
            try:
                supabase.table("phrases").delete().eq("deck_name", deck_name).execute()
                supabase.table("decks").delete().eq("name", deck_name).execute()
                st.toast(f"Deleted deck '{deck_name}'")
                st.rerun()
            except Exception as e:
                st.error(f"Error deleting deck: {e}")

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
            if st.button("🗑️ Delete Deck", type="secondary", use_container_width=True):
                if selected_deck:
                    confirm_delete_dialog(selected_deck)

        if selected_deck:
            try:
                phrases_res = supabase.table("phrases").select("*").eq("deck_name", selected_deck).execute()
                phrases_data = phrases_res.data if phrases_res.data else []
            except Exception as e:
                phrases_data = []
                st.error(f"Error loading phrases for deck '{selected_deck}': {e}")
            
            st.caption(f"Loaded Deck: **{selected_deck}** ({len(phrases_data)} phrases)")
            
            # --- EDIT DECK & PHRASES EXPANDER ---
            with st.expander("✏️ Edit Deck Name & Phrases"):
                new_deck_name = st.text_input("Rename Deck", value=selected_deck, key=f"rename_deck_input_{selected_deck}")
                if st.button("Update Deck Name", key=f"update_deck_btn_{selected_deck}"):
                    if new_deck_name and new_deck_name != selected_deck:
                        try:
                            supabase.table("decks").upsert({"name": new_deck_name}).execute()
                            supabase.table("phrases").update({"deck_name": new_deck_name}).eq("deck_name", selected_deck).execute()
                            supabase.table("decks").delete().eq("name", selected_deck).execute()
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

            # Toggle expander state for practice settings cleanly
            settings_open = st.toggle("⚙️ Practice Settings", value=False, key="toggle_settings")
            
            if settings_open:
                c1, c2, c3, c4 = st.columns(4)
                
                with c1:
                    speed_choice = st.selectbox(
                        "Speech Speed",
                        ["Normal", "Slow", "Slower", "Slowest", "Faster"],
                        index=0,
                        key="setting_speed"
                    )
                with c2:
                    repetitions = st.number_input("Repetitions per phrase", min_value=1, max_value=5, value=1, key="setting_reps")
                with c3:
                    pause_duration = st.number_input("Pause between phrases (s)", 1.0, 10.0, 2.0, 0.5, key="setting_pause")
                with c4:
                    reverse_recall = st.checkbox("Reverse Recall (Show EN, play ES)", value=False, key="setting_reverse")
                    show_translation = st.checkbox("Show Translations", value=True, key="setting_show_trans")
            else:
                speed_choice = st.session_state.get("setting_speed", "Normal")
                repetitions = st.session_state.get("setting_reps", 1)
                pause_duration = st.session_state.get("setting_pause", 2.0)
                reverse_recall = st.session_state.get("setting_reverse", False)
                show_translation = st.session_state.get("setting_show_trans", True)

            rate_mapping = {
                "Normal": "+0%",
                "Slow": "-20%",
                "Slower": "-30%",
                "Slowest": "-40%",
                "Faster": "+15%"
            }
            selected_rate = rate_mapping[speed_choice]
            
            st.divider()
            
            # Global Drill Controls
            col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
            with col_p1:
                if st.button("▶️ Start / Restart Drill", type="primary", use_container_width=True, key="start_drill_btn"):
                    st.session_state["drill_active"] = True
                    st.session_state["drill_paused"] = False
                    st.session_state["current_phrase_idx"] = 0
                    st.rerun()
                    
            with col_p2:
                pause_label = "▶️ Resume Drill" if st.session_state["drill_paused"] else "⏸️ Pause Drill"
                if st.button(pause_label, use_container_width=True, key="pause_drill_btn", disabled=not st.session_state["drill_active"]):
                    st.session_state["drill_paused"] = not st.session_state["drill_paused"]
                    st.rerun()
                    
            with col_p3:
                if st.button("⏹️ Stop Drill", type="secondary", use_container_width=True, key="stop_drill_btn", disabled=not st.session_state["drill_active"]):
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
                    
                    border_color = "#ffc107" if st.session_state["drill_paused"] else "#30363d"
                    status_badge = " <span style='color:#ffc107; font-size:0.9rem;'>(PAUSED)</span>" if st.session_state["drill_paused"] else ""
                    
                    # Centered focus container with fixed height viewport
                    st.markdown(f"""
                    <div style="height: 220px; display: flex; align-items: center; justify-content: center; background-color: #0d1117; border-radius: 10px; border: 1px solid {border_color}; margin: 10px 0; padding: 20px;">
                        <div style="text-align: center;">
                            <h2 style="color: #ffffff; font-size: 1.8rem !important; margin: 0 0 10px 0 !important;">{main_text}{status_badge}</h2>
                            <h4 style="color: #8b949e; font-size: 1.1rem; font-weight: 400; margin: 0;">{sub_text}</h4>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    inject_drill_helpers(st.session_state["drill_active"])
                    
                    # Navigation Controls directly beneath card
                    col_nav1, col_nav2 = st.columns([1, 1])
                    with col_nav1:
                        if st.button("⬅️ Previous", use_container_width=True, disabled=curr_idx == 0):
                            if st.session_state["current_phrase_idx"] > 0:
                                st.session_state["current_phrase_idx"] -= 1
                                st.rerun()
                    with col_nav2:
                        if st.button("➡️ Next", use_container_width=True, disabled=curr_idx >= len(phrases_data) - 1):
                            if st.session_state["current_phrase_idx"] < len(phrases_data) - 1:
                                st.session_state["current_phrase_idx"] += 1
                                st.rerun()

                    # Audio Playback Loop (Only triggers when NOT paused)
                    if not st.session_state["drill_paused"]:
                        audio_bytes = get_audio_bytes(target, rate_str=selected_rate)
                        
                        if audio_bytes:
                            audio_duration = len(audio_bytes) / 6000.0
                            
                            thinking_time = (pause_duration * 0.5) if reverse_recall else 0
                            post_audio_pause = pause_duration - thinking_time if reverse_recall else pause_duration

                            if thinking_time > 0:
                                time.sleep(thinking_time)
                            
                            for rep in range(repetitions):
                                play_audio_silently(audio_bytes)
                                time.sleep(audio_duration)
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
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
                
            st.write("File preview (first 5 rows):")
            st.dataframe(df.head())
            
            if st.button("Save Deck to Supabase", type="primary"):
                if not deck_title_input.strip():
                    st.warning("Please enter a valid Deck Name before saving.")
                else:
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
               
