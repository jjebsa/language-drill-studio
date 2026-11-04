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

if not supabase:
    st.error("⚠️ Supabase credentials missing! Please configure `SUPABASE_URL` and `SUPABASE_KEY` in Streamlit Secrets.")
    st.stop()

# --- INITIALIZE SESSION STATE & PERSISTENT DEFAULTS ---
if "setting_speed" not in st.session_state:
    st.session_state["setting_speed"] = "Normal"
if "setting_reps" not in st.session_state:
    st.session_state["setting_reps"] = 1
if "setting_pause" not in st.session_state:
    st.session_state["setting_pause"] = 2.0
if "setting_reverse" not in st.session_state:
    st.session_state["setting_reverse"] = False
if "setting_show_trans" not in st.session_state:
    st.session_state["setting_show_trans"] = True

if "drill_active" not in st.session_state:
    st.session_state["drill_active"] = False
if "drill_paused" not in st.session_state:
    st.session_state["drill_paused"] = False
if "current_phrase_idx" not in st.session_state:
    st.session_state["current_phrase_idx"] = 0

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
    if not audio_bytes:
        return
    b64 = base64.b64encode(audio_bytes).decode()
    audio_html = f'<audio autoplay="true" src="data:audio/mp3;base64,{b64}"></audio>'
    st.markdown(audio_html, unsafe_allow_html=True)

def inject_drill_helpers(is_active):
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
            supabase.table("phrases").delete().eq("deck_name", deck_name).execute()
            supabase.table("decks").delete().eq("name", deck_name).execute()
            st.toast(f"Deleted deck '{deck_name}'")
            st.rerun()

# --- PROMINENT TOP-LEVEL TABS ---
tab_practice, tab_upload, tab_paste = st.tabs([
    "🗣️ Practice Studio",
    "📁 Upload File",
    "✍️ Type / Paste"
])

# ==========================================
# TAB 1: PRACTICE STUDIO & LIBRARY
# ==========================================
with tab_practice:
    try:
        decks_res = supabase.table("decks").select("name").execute()
        deck_names = [d["name"] for d in decks_res.data] if decks_res.data else []
    except Exception as e:
        deck_names = []
        st.warning(f"Could not load decks from Supabase: {e}")

    if not deck_names:
        st.info("No decks found in Supabase yet. Use the 'Upload File' or 'Type / Paste' tabs above to add your first deck!")
    else:
        top_col1, top_col2 = st.columns([1.5, 2.5])
        with top_col1:
            st.markdown("### 🗣️ Practice Studio")
            st.markdown("Listen and Repeat, Shadowing, Active Recall")
            video_id = "43IrHhD8biA"
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

            html_content = f"""
            <div style="text-align: center; margin: 10px 0;">
                <a href="https://www.youtube.com/watch?v={video_id}" target="_blank">
                    <img src="{thumbnail_url}" width="120" style="border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);">
                </a>
                <p style="font-size: 0.85em; color: white; margin-top: 6px;">▶ Tap on image to watch "What is Active Recall" on YouTube</p>
            </div>
            """
            st.markdown(html_content, unsafe_allow_html=True)
        with top_col2:
            st.caption("#### Select a Deck to Practice ↴")
            selected_deck = st.selectbox("Select Deck:", deck_names, key="active_deck_select", label_visibility="collapsed")

        if selected_deck:
            try:
                phrases_res = supabase.table("phrases").select("*").eq("deck_name", selected_deck).execute()
                phrases_data = phrases_res.data if phrases_res.data else []
            except Exception as e:
                phrases_data = []
                st.error(f"Error loading phrases for deck '{selected_deck}': {e}")
            
            with st.expander("✏️ Click to Edit Deck:  Rename Deck, Add/Edit Phrases, delete deck."):
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

                st.markdown("---")
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

                st.markdown("---")
                st.markdown("### Danger Zone")
                if st.button("🗑️ Delete Selected Deck", type="secondary"):
                    confirm_delete_dialog(selected_deck)

            # --- SETTINGS EXPANDER (Persistent & Cleanly Bound to Session State) ---
            with st.expander("⚙️ SETTINGS: Voice Speed, Repetions per Pair, Pause Between Pairs, Show Translation, Select Recall Mode", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    speed_choice = st.selectbox(
                        "Speed", 
                        ["Normal", "Slow", "Slower", "Slowest", "Faster"], 
                        key="setting_speed"
                    )
                with c2:
                    repetitions = st.number_input(
                        "Reps", 
                        min_value=1, 
                        max_value=5, 
                        key="setting_reps"
                    )
                with c3:
                    pause_duration = st.number_input(
                        "Pause (s)", 
                        min_value=1.0, 
                        max_value=10.0, 
                        step=0.5, 
                        key="setting_pause"
                    )
                with c4:
                    reverse_recall = st.checkbox(
                        "Recall Mode (EN->ES)", 
                        key="setting_reverse"
                    )
                    show_translation = st.checkbox(
                        "Show Translation Off/On", 
                        key="setting_show_trans"
                    )

            # Pull active settings directly from session state variables
            speed_choice = st.session_state["setting_speed"]
            repetitions = st.session_state["setting_reps"]
            pause_duration = st.session_state["setting_pause"]
            reverse_recall = st.session_state["setting_reverse"]
            show_translation = st.session_state["setting_show_trans"]

            rate_mapping = {
                "Normal": "+0%",
                "Slow": "-20%",
                "Slower": "-30%",
                "Slowest": "-40%",
                "Faster": "+15%"
            }
            selected_rate = rate_mapping[speed_choice]
            
            if st.session_state["drill_active"] and phrases_data:
                curr_idx = st.session_state["current_phrase_idx"]
                
                if curr_idx < len(phrases_data):
                    p = phrases_data[curr_idx]
                    target = p.get("spanish", "")
                    translation = p.get("english", "")
                    
                    if reverse_recall:
                        main_text = translation if translation else "(No translation)"
                        sub_text = target if show_translation else "🔊 [Recall Spanish]"
                    else:
                        main_text = target
                        sub_text = f"*{translation}*" if show_translation else ""
                    
                    border_color = "#ffc107" if st.session_state["drill_paused"] else "#30363d"
                    status_badge = " <span style='color:#ffc107; font-size:0.8rem;'>(PAUSED)</span>" if st.session_state["drill_paused"] else ""
                    
                    st.markdown(f"""
                    <div style="min-height: 190px; display: flex; align-items: center; justify-content: center; background-color: #0d1117; border-radius: 8px; border: 1px solid {border_color}; margin: 5px 0; padding: 12px 16px;">
                        <div style="text-align: center; width: 100%;">
                            <div style="color: #ffffff; font-size: 1.15rem; font-weight: 600; line-height: 1.3; margin-bottom: 8px;">{main_text}{status_badge}</div>
                            <div style="color: #8b949e; font-size: 0.9rem; font-weight: 400; margin: 0;">{sub_text}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    inject_drill_helpers(st.session_state["drill_active"])
                    
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

            st.divider()
            
            col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
            with col_p1:
                if st.button("▶️ Start / Restart", type="primary", use_container_width=True, key="start_drill_btn"):
                    st.session_state["drill_active"] = True
                    st.session_state["drill_paused"] = False
                    st.session_state["current_phrase_idx"] = 0
                    st.rerun()
                    
            with col_p2:
                pause_label = "▶️ Resume" if st.session_state["drill_paused"] else "⏸️ Pause"
                if st.button(pause_label, use_container_width=True, key="pause_drill_btn", disabled=not st.session_state["drill_active"]):
                    st.session_state["drill_paused"] = not st.session_state["drill_paused"]
                    st.rerun()
                    
            with col_p3:
                if st.button("⏹️ Stop", type="secondary", use_container_width=True, key="stop_drill_btn", disabled=not st.session_state["drill_active"]):
                    st.session_state["drill_active"] = False
                    st.session_state["drill_paused"] = False
                    st.session_state["current_phrase_idx"] = 0
                    st.rerun()

            # --- DRILL AUTO-ADVANCE & ACCURATE AUDIO TIMING LOOP ---
            if st.session_state["drill_active"] and not st.session_state["drill_paused"] and phrases_data:
                curr_idx = st.session_state["current_phrase_idx"]
                if curr_idx < len(phrases_data):
                    p = phrases_data[curr_idx]
                    target = p.get("spanish", "")
                    
                    audio_bytes = get_audio_bytes(target, rate_str=selected_rate)
                    if audio_bytes:
                        # Calculate exact audio duration from bytes to prevent audio overlap
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
                    
                    if st.session_state["current_phrase_idx"] < len(phrases_data) - 1:
                        st.session_state["current_phrase_idx"] += 1
                        st.rerun()
                    else:
                        st.session_state["drill_active"] = False
                        st.success("🎉 Drill completed!")
                        st.rerun()

            st.divider()
            
            with st.expander(f"📋 Click to view Phrase List and play Individual Phrases ({len(phrases_data)} items)"):
                for idx, p in enumerate(phrases_data, 1):
                    target = p.get("spanish", "")
                    translation = p.get("english", "")
                    
                    row_cols = st.columns([4, 1])
                    with row_cols[0]:
                        if reverse_recall:
                            display_str = f"**{idx}.** {translation} &nbsp;|&nbsp; *(Think Spanish)*"
                        elif show_translation:
                            display_str = f"**{idx}.** {target} &nbsp;|&nbsp; *{translation}*"
                        else:
                            display_str = f"**{idx}.** {target}"
                        st.markdown(display_str)
                    with row_cols[1]:
                        if st.button("▶", key=f"play_single_{idx}"):
                            audio_data = get_audio_bytes(target, rate_str=selected_rate)
                            if audio_data:
                                play_audio_silently(audio_data)

# ==========================================
# TAB 2: UPLOAD CSV / TSV FILE
# ==========================================
with tab_upload:
    # --- RESET CHECK (Must be before widgets are created) ---
    if st.session_state.get("clear_upload_form", False):
        st.session_state["upload_deck_title"] = ""
        st.session_state["clear_upload_form"] = False
    # --------------------------------------------------------

    st.markdown("### Upload Bilingual Phrase File")
    
    uploaded_file = st.file_uploader("Choose a premade .CSV, .TSV, or .TXT file from your device. ( 2 columns: target language 1st, translation 2nd. Separated by pipe ( | ), comma, or tab", type=["csv", "tsv", "txt"], key="upload_file_widget")
    deck_title_input = st.text_input("Enter a Name for your New Deck", placeholder="Imported Deck", key="upload_deck_title")
    
    if uploaded_file is not None:
        try:
            content = uploaded_file.getvalue().decode("utf-8", errors="ignore")
            first_lines = "\n".join(content.splitlines()[:5])
            
            sep = ","
            if ";" in first_lines and first_lines.count(";") >= first_lines.count(","):
                sep = ";"
            elif "\t" in first_lines:
                sep = "\t"
            elif "|" in first_lines:
                sep = "|"
            
            import io
            # Added header=None so pandas doesn't accidentally skip your first row of phrases
            df = pd.read_csv(io.StringIO(content), sep=sep, header=None)
            
            if len(df.columns) == 1:
                for alt_sep in [",", ";", "\t", "|"]:
                    df_test = pd.read_csv(io.StringIO(content), sep=alt_sep, header=None)
                    if len(df_test.columns) > 1:
                        df = df_test
                        sep = alt_sep
                        break
            
            st.write(f"File preview (Detected separator: `{repr(sep)}`):")
            st.dataframe(df.head(3), height=150)
            
            if st.button("Save Deck to Supabase", type="primary"):
                if not deck_title_input.strip():
                    st.warning("Please enter a valid Deck Name.")
                else:
                    with st.spinner("Saving..."):
                        supabase.table("decks").upsert({"name": deck_title_input.strip()}).execute()
                        cols = {str(c).lower().strip(): c for c in df.columns}
                        
                        col_es = cols.get('spanish', cols.get('es', 0))
                        col_en = cols.get('english', cols.get('en', 1 if len(df.columns) > 1 else 0))
                        
                        success_count = 0
                        for _, row in df.iterrows():
                            spanish_val = str(row[col_es]).strip() if pd.notna(row[col_es]) else ""
                            english_val = str(row[col_en]).strip() if pd.notna(row[col_en]) else ""
                            if spanish_val and spanish_val != "nan":
                                supabase.table("phrases").insert({
                                    "deck_name": deck_title_input.strip(),
                                    "spanish": spanish_val,
                                    "english": english_val
                                }).execute()
                                success_count += 1
                        
                        st.success(f"Saved '{deck_title_input}' ({success_count} phrases)!")
                        
                        # Trigger the flag instead of modifying the widget state directly
                        st.session_state["clear_upload_form"] = True
                        time.sleep(0.8)
                        st.rerun()
        except Exception as e:
            st.error(f"Error parsing file: {e}")

# ==========================================
# TAB 3: TYPE or PASTE PHRASES
# ==========================================
with tab_paste:
    if st.session_state.get("clear_paste_form", False):
       st.session_state["paste_raw_text"] = ""
       st.session_state["paste_deck_title"] = ""
       st.session_state["clear_paste_form"] = False

    st.markdown("### ✍️ Type or Paste Words and Phrases")
    st.markdown("You can enter multiple pairs here. Be sure to use the separation symbols between your target language and its translation, either pipe (`|`) or comma.") 
    st.caption("*Optionally, enter one pair, then *SAVE DECK*, then add more lines under *EDIT DECK* in the *PRACTICE STUDIO*. May be easier if typing rather than pasting.*")

    raw_text = st.text_area(
        "Enter your Phrase or Word Pairs", 
        placeholder="Hola | Hello\n¿Cómo estás? , How are you?", 
        height=150,
        key="paste_raw_text"
    )
    deck_title = st.text_input("Enter a Name for your New Deck and click Save Deck", placeholder="My Deck Name", key="paste_deck_title")
    
    if st.button("Save Deck", type="primary"):
        if not raw_text.strip():
            st.warning("Please enter phrase pairs.")
        elif not deck_title.strip():
            st.warning("Please enter a deck title.")
        else:
            lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
            supabase.table("decks").upsert({"name": deck_title.strip()}).execute()
            
            for line in lines:
                if "|" in line:
                    parts = line.split("|", 1)
                elif "\t" in line:
                    parts = line.split("\t", 1)
                elif "\\t" in line:
                    parts = line.split("\\t", 1)
                elif "," in line:
                    parts = line.split(",", 1)
                else:
                    parts = [line, line]
                
                spanish_text = parts[0].strip()
                english_text = parts[1].strip() if len(parts) > 1 else spanish_text
                
                supabase.table("phrases").insert({
                    "deck_name": deck_title.strip(),
                    "spanish": spanish_text,
                    "english": english_text
                }).execute()
            
            st.success(f"Saved deck '{deck_title}' with {len(lines)} phrases!")
            st.session_state["clear_paste_form"] = True
            time.sleep(0.8)
            st.rerun()
