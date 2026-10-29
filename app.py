import streamlit as st
import asyncio
import edge_tts
import os
import subprocess
import csv
import io
import json
import base64
from deep_translator import GoogleTranslator

st.set_page_config(page_title="Spanish Audio Drill Generator", layout="centered")

st.title("🇪🇸 Spanish Listening Drill Studio")

LIBRARY_DIR = "saved_lists"
AUDIO_DIR = "audio_cache"
os.makedirs(LIBRARY_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# --- Session State Setup ---
if "current_pairs" not in st.session_state:
    st.session_state.current_pairs = None
if "selected_deck" not in st.session_state:
    st.session_state.selected_deck = None

def parse_and_translate(content, filename=None):
    """Parses CSV content, preserves full sentences containing commas, translates single columns, and updates file."""
    translator = GoogleTranslator(source='es', target='en')
    pairs = []
    translations_added = False

    f_csv = io.StringIO(content.strip())
    reader = list(csv.reader(f_csv))
    
    if not reader:
        return pairs

    has_explicit_en_col = False
    start_idx = 0

    # Inspect first row for explicit 2-column header
    first_row = [field.strip().lower() for field in reader[0] if field.strip()]
    if first_row:
        if len(first_row) >= 2 and first_row[0] in ["spanish", "phrase", "text", "es"] and first_row[1] in ["english", "translation", "en"]:
            has_explicit_en_col = True
            start_idx = 1
        elif len(first_row) == 1 and first_row[0] in ["spanish", "phrase", "text", "es"]:
            start_idx = 1

    for row in reader[start_idx:]:
        clean_fields = [f.strip().strip('"').strip("'") for f in row if f.strip()]
        if not clean_fields:
            continue

        if has_explicit_en_col and len(clean_fields) >= 2:
            es = clean_fields[0]
            en = clean_fields[1]
        else:
            # Single-column list: recombine any fields split by commas back into full Spanish phrase
            es = ", ".join(clean_fields)
            en = ""

        if es:
            if not en:
                try:
                    en = translator.translate(es)
                except Exception:
                    en = "Translation unavailable"
                translations_added = True
            pairs.append((es, en))

    # Overwrite library file with full [spanish, english] columns if translations were generated
    if translations_added and filename:
        file_path = os.path.join(LIBRARY_DIR, filename)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["spanish", "english"])
            for es_text, en_text in pairs:
                writer.writerow([es_text, en_text])

    return pairs

async def generate_phrase_chunks(phrases, deck_folder, voice):
    """Generates individual TTS mp3 chunks for each sentence in a deck."""
    os.makedirs(deck_folder, exist_ok=True)
    for idx, text in enumerate(phrases):
        chunk_path = os.path.join(deck_folder, f"{idx}.mp3")
        if not os.path.exists(chunk_path):
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(chunk_path)

# --- Phrase Library Management ---
st.subheader("📚 Phrase Library")

tab_upload, tab_type = st.tabs(["📁 Upload CSV File", "✍️ Type / Paste Spanish Phrases"])

with tab_upload:
    uploaded_file = st.file_uploader("Upload New Phrase CSV", type=["csv"], key="uploader")
    if uploaded_file:
        file_name = uploaded_file.name
        save_path = os.path.join(LIBRARY_DIR, file_name)
        
        if not os.path.exists(save_path):
            raw_bytes = uploaded_file.getvalue()
            with open(save_path, "wb") as f:
                f.write(raw_bytes)
            st.session_state.selected_deck = file_name
            st.toast(f"Saved '{file_name}' to library!", icon="💾")
            st.rerun()

with tab_type:
    deck_title = st.text_input("Deck Name", placeholder="e.g., Local_Phrases", key="input_deck_name")
    
    # Language direction toggle
    input_lang = st.radio(
        "Input Language:", 
        ["Spanish", "English"], 
        horizontal=True, 
        key="input_lang_radio"
    )
    
    typed_phrases = st.text_area(
        f"Enter {input_lang} phrases (one per line):", 
        height=140, 
        placeholder="¿Dónde está el ayuntamiento?\nMe gustaría comprar un kilo de naranjas, por favor." if input_lang == "Spanish" else "Where is the town hall?\nI would like to buy a kilo of oranges, please.", 
        key="input_phrases"
    )
    
    if st.button("Save as New CSV Deck", key="btn_save_typed"):
        if not deck_title.strip():
            st.error("Please enter a deck name.")
        elif not typed_phrases.strip():
            st.error("Please enter at least one phrase.")
        else:
            clean_title = deck_title.strip().replace(" ", "_")
            if not clean_title.lower().endswith(".csv"):
                clean_title += ".csv"
            save_path = os.path.join(LIBRARY_DIR, clean_title)
            
            phrases_list = [p.strip() for p in typed_phrases.splitlines() if p.strip()]
            
            with st.spinner("Translating and creating deck..."):
                with open(save_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    if input_lang == "English":
                        # Translate English input to Spanish for audio playback
                        translator = GoogleTranslator(source='en', target='es')
                        writer.writerow(["spanish", "english"])
                        for en_phrase in phrases_list:
                            try:
                                es_phrase = translator.translate(en_phrase)
                            except Exception:
                                es_phrase = en_phrase
                            writer.writerow([es_phrase, en_phrase])
                    else:
                        # Spanish input (translated to EN automatically on deck load)
                        writer.writerow(["spanish"])
                        for phrase in phrases_list:
                            writer.writerow([phrase])
            
            st.session_state.selected_deck = clean_title
            st.toast(f"Created deck '{clean_title}'!", icon="🎉")
            st.rerun()

st.divider()

saved_files = sorted([f for f in os.listdir(LIBRARY_DIR) if f.endswith('.csv')])

if saved_files:
    col_select, col_delete = st.columns([3, 1])
    with col_select:
        selected_deck = st.selectbox(
            "Select a Phrase Deck:", 
            saved_files, 
            index=saved_files.index(st.session_state.selected_deck) if st.session_state.selected_deck in saved_files else 0,
            key="deck_selector"
        )
        st.session_state.selected_deck = selected_deck
        
    with col_delete:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🗑️ Delete", type="secondary", use_container_width=True, key="btn_delete"):
            os.remove(os.path.join(LIBRARY_DIR, selected_deck))
            
            deck_base = os.path.splitext(selected_deck)[0]
            cache_folder = os.path.join(AUDIO_DIR, deck_base)
            if os.path.exists(cache_folder):
                for f in os.listdir(cache_folder):
                    os.remove(os.path.join(cache_folder, f))
                os.rmdir(cache_folder)

            st.session_state.selected_deck = None
            st.session_state.current_pairs = None
            st.toast(f"Deleted '{selected_deck}'")
            st.rerun()

    file_path = os.path.join(LIBRARY_DIR, selected_deck)
    with open(file_path, "r", encoding="utf-8-sig") as f:
        st.session_state.current_pairs = parse_and_translate(f.read(), selected_deck)

else:
    st.info("No CSV decks available. Upload a CSV file or type phrases above to get started.")

st.divider()

# --- Voice Selection & Generator ---
if st.session_state.current_pairs and st.session_state.selected_deck:
    deck_base = os.path.splitext(st.session_state.selected_deck)[0]
    deck_audio_folder = os.path.join(AUDIO_DIR, deck_base)
    
    voice = st.selectbox(
        "Voice Model", 
        ["es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-ES-XimenaNeural"], 
        key="voice_select"
    )
    
    spanish_phrases = [p[0] for p in st.session_state.current_pairs]
    
    if st.button("🚀 Prepare / Rebuild Audio Chunks", use_container_width=True, key="btn_prep_audio"):
        with st.spinner("Generating audio for sentences..."):
            if os.path.exists(deck_audio_folder):
                for f in os.listdir(deck_audio_folder):
                    os.remove(os.path.join(deck_audio_folder, f))
            asyncio.run(generate_phrase_chunks(spanish_phrases, deck_audio_folder, voice))
        st.toast("Audio prepared successfully!")
        st.rerun()

    chunks_exist = os.path.exists(deck_audio_folder) and len(os.listdir(deck_audio_folder)) >= len(spanish_phrases)
    if not chunks_exist:
        with st.spinner("Preparing initial sentence audio..."):
            asyncio.run(generate_phrase_chunks(spanish_phrases, deck_audio_folder, voice))
            chunks_exist = True

    # --- Synced Interactive Drill Player ---
    if chunks_exist:
        st.divider()
        st.subheader("🎧 Synced Practice Studio")

        audio_data_uris = []
        for i in range(len(spanish_phrases)):
            chunk_file = os.path.join(deck_audio_folder, f"{i}.mp3")
            if os.path.exists(chunk_file):
                with open(chunk_file, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    audio_data_uris.append(f"data:audio/mp3;base64,{b64}")
            else:
                audio_data_uris.append("")

        deck_payload = json.dumps([
            {"es": es, "en": en, "audio": uri}
            for (es, en), uri in zip(st.session_state.current_pairs, audio_data_uris)
        ])

        player_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    background-color: transparent;
                    color: #1f2937;
                    margin: 0;
                    padding: 0;
                }}
                .player-card {{
                    border: 1px solid #e5e7eb;
                    border-radius: 12px;
                    padding: 24px;
                    background-color: #ffffff;
                    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
                }}
                .controls-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                    gap: 16px;
                    margin-bottom: 20px;
                    background: #f9fafb;
                    padding: 16px;
                    border-radius: 8px;
                }}
                .control-group {{
                    display: flex;
                    flex-direction: column;
                }}
                .control-group label {{
                    font-size: 0.85rem;
                    font-weight: 600;
                    color: #4b5563;
                    margin-bottom: 4px;
                }}
                .control-group input[type="range"], .control-group select {{
                    width: 100%;
                }}
                .card-display {{
                    min-height: 140px;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    text-align: center;
                    background-color: #f3f4f6;
                    border-radius: 10px;
                    padding: 20px;
                    margin-bottom: 20px;
                }}
                .es-text {{
                    font-size: 1.5rem;
                    font-weight: 700;
                    color: #111827;
                    margin-bottom: 8px;
                }}
                .en-text {{
                    font-size: 1.1rem;
                    color: #6b7280;
                    font-style: italic;
                }}
                .nav-bar {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 12px;
                }}
                .btn {{
                    background-color: #2563eb;
                    color: white;
                    border: none;
                    padding: 10px 18px;
                    font-size: 0.95rem;
                    font-weight: 600;
                    border-radius: 6px;
                    cursor: pointer;
                    transition: background 0.2s;
                }}
                .btn:hover {{
                    background-color: #1d4ed8;
                }}
                .btn-secondary {{
                    background-color: #4b5563;
                }}
                .btn-secondary:hover {{
                    background-color: #374151;
                }}
                .btn:disabled {{
                    background-color: #d1d5db;
                    cursor: not-allowed;
                }}
                .counter-text {{
                    font-weight: 600;
                    color: #374151;
                }}
            </style>
        </head>
        <body>
            <div class="player-card">
                <div class="controls-grid">
                    <div class="control-group">
                        <label>Speed: <span id="speedVal">1.0x</span></label>
                        <input type="range" id="speedSlider" min="0.5" max="1.5" step="0.1" value="1.0">
                    </div>
                    <div class="control-group">
                        <label>Repeats: <span id="repeatVal">2</span></label>
                        <input type="range" id="repeatSlider" min="1" max="5" step="1" value="2">
                    </div>
                    <div class="control-group">
                        <label>Pause Gap: <span id="pauseVal">3.0s</span></label>
                        <input type="range" id="pauseSlider" min="1.0" max="6.0" step="0.5" value="3.0">
                    </div>
                    <div class="control-group">
                        <label>Translation</label>
                        <button class="btn btn-secondary" id="toggleEnBtn" style="padding: 6px 12px; font-size: 0.85rem;">Toggle English</button>
                    </div>
                </div>

                <div class="card-display">
                    <div class="es-text" id="esDisplay">---</div>
                    <div class="en-text" id="enDisplay" style="display: none;">---</div>
                </div>

                <div class="nav-bar">
                    <button class="btn btn-secondary" id="prevBtn">⬅️ Previous</button>
                    <button class="btn" id="playPauseBtn">▶️ Play Drill</button>
                    <span class="counter-text" id="counterDisplay">Sentence 1 of 1</span>
                    <button class="btn btn-secondary" id="nextBtn">Next ➡️</button>
                </div>
            </div>

            <script>
                const deck = {deck_payload};
                let currentIndex = 0;
                let currentRepeat = 0;
                let isPlaying = false;
                let showEnglish = false;
                let timerId = null;
                let currentAudio = null;

                const esDisplay = document.getElementById('esDisplay');
                const enDisplay = document.getElementById('enDisplay');
                const counterDisplay = document.getElementById('counterDisplay');
                const playPauseBtn = document.getElementById('playPauseBtn');
                const prevBtn = document.getElementById('prevBtn');
                const nextBtn = document.getElementById('nextBtn');
                const toggleEnBtn = document.getElementById('toggleEnBtn');

                const speedSlider = document.getElementById('speedSlider');
                const repeatSlider = document.getElementById('repeatSlider');
                const pauseSlider = document.getElementById('pauseSlider');

                const speedVal = document.getElementById('speedVal');
                const repeatVal = document.getElementById('repeatVal');
                const pauseVal = document.getElementById('pauseVal');

                function updateCard() {{
                    const item = deck[currentIndex];
                    esDisplay.innerText = item.es;
                    enDisplay.innerText = item.en || '';
                    enDisplay.style.display = showEnglish ? 'block' : 'none';
                    counterDisplay.innerText = `Sentence ${{currentIndex + 1}} of ${{deck.length}}`;

                    prevBtn.disabled = currentIndex === 0;
                    nextBtn.disabled = currentIndex === deck.length - 1;
                }}

                function playSentence() {{
                    if (!isPlaying) return;

                    stopAudio();
                    const item = deck[currentIndex];
                    if (!item.audio) return;

                    currentAudio = new Audio(item.audio);
                    currentAudio.playbackRate = parseFloat(speedSlider.value);

                    currentAudio.onended = () => {{
                        currentRepeat++;
                        const totalRepeats = parseInt(repeatSlider.value);
                        const pauseGapMs = parseFloat(pauseSlider.value) * 1000;

                        if (currentRepeat < totalRepeats) {{
                            timerId = setTimeout(playSentence, pauseGapMs);
                        }} else {{
                            if (currentIndex < deck.length - 1) {{
                                timerId = setTimeout(() => {{
                                    currentIndex++;
                                    currentRepeat = 0;
                                    updateCard();
                                    playSentence();
                                }}, pauseGapMs);
                            }} else {{
                                timerId = setTimeout(() => {{
                                    stopDrill();
                                }}, pauseGapMs);
                            }}
                        }}
                    }};

                    currentAudio.play();
                }}

                function stopAudio() {{
                    if (timerId) clearTimeout(timerId);
                    if (currentAudio) {{
                        currentAudio.pause();
                        currentAudio = null;
                    }}
                }}

                function stopDrill() {{
                    isPlaying = false;
                    stopAudio();
                    playPauseBtn.innerText = '▶️ Play Drill';
                }}

                function startDrill() {{
                    isPlaying = true;
                    currentRepeat = 0;
                    playPauseBtn.innerText = '⏸️ Pause';
                    playSentence();
                }}

                playPauseBtn.addEventListener('click', () => {{
                    if (isPlaying) {{
                        stopDrill();
                    }} else {{
                        startDrill();
                    }}
                }});

                prevBtn.addEventListener('click', () => {{
                    if (currentIndex > 0) {{
                        stopAudio();
                        currentIndex--;
                        currentRepeat = 0;
                        updateCard();
                        if (isPlaying) playSentence();
                    }}
                }});

                nextBtn.addEventListener('click', () => {{
                    if (currentIndex < deck.length - 1) {{
                        stopAudio();
                        currentIndex++;
                        currentRepeat = 0;
                        updateCard();
                        if (isPlaying) playSentence();
                    }}
                }});

                toggleEnBtn.addEventListener('click', () => {{
                    showEnglish = !showEnglish;
                    updateCard();
                }});

                speedSlider.addEventListener('input', (e) => {{
                    speedVal.innerText = e.target.value + 'x';
                    if (currentAudio) {{
                        currentAudio.playbackRate = parseFloat(e.target.value);
                    }}
                }});

                repeatSlider.addEventListener('input', (e) => {{
                    repeatVal.innerText = e.target.value;
                }});

                pauseSlider.addEventListener('input', (e) => {{
                    pauseVal.innerText = e.target.value + 's';
                }});

                updateCard();
            </script>
        </body>
        </html>
        """

        st.iframe(player_html, height=520)

        with st.expander("📦 Optional: Stitch into Single MP3 File for Offline / Mobile Use"):
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                export_speed = st.slider("Export Speed (%)", -40, 20, -15, step=5, key="exp_speed")
                export_repeats = st.slider("Export Repeats", 1, 5, 2, key="exp_repeats")
            with col_exp2:
                export_pause = st.slider("Export Pause (sec)", 1.0, 6.0, 3.0, step=0.5, key="exp_pause")

            if st.button("Generate Combined MP3 File", key="btn_stitch_mp3"):
                combined_mp3_path = os.path.join(AUDIO_DIR, f"{deck_base}_combined.mp3")
                output_dir = os.path.join(AUDIO_DIR, "temp_chunks")
                os.makedirs(output_dir, exist_ok=True)

                with st.spinner("Stitching sentences, pauses, and adjusting audio tempo with ffmpeg..."):
                    silence_path = os.path.join(output_dir, f"silence_{export_pause}s.mp3")
                    subprocess.run(
                        f'ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t {export_pause} -c:a libmp3lame -y "{silence_path}"',
                        shell=True, capture_output=True
                    )

                    filelist = []
                    for idx in range(len(spanish_phrases)):
                        chunk_path = os.path.join(deck_audio_folder, f"{idx}.mp3")
                        for _ in range(export_repeats):
                            filelist.append(f"file '{os.path.abspath(chunk_path).replace('\\\\', '/')}'")
                            filelist.append(f"file '{os.path.abspath(silence_path).replace('\\\\', '/')}'")

                    manifest_path = os.path.join(output_dir, "manifest.txt")
                    with open(manifest_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(filelist))

                    # Calculate tempo multiplier (e.g., -15% -> 0.85, +20% -> 1.20)
                    speed_factor = 1.0 + (export_speed / 100.0)

                    subprocess.run(
                        f'ffmpeg -f concat -safe 0 -i "{manifest_path}" -filter:a "atempo={speed_factor:.2f}" -c:a libmp3lame -q:a 2 -y "{combined_mp3_path}"',
                        shell=True, capture_output=True
                    )

                st.success("Single MP3 generated!")
                st.audio(combined_mp3_path)
                with open(combined_mp3_path, "rb") as f:
                    st.download_button(
                        "📥 Download Combined MP3",
                        f,
                        file_name=f"{deck_base}_drill.mp3",
                        use_container_width=True,
                        key="dl_stitched"
                    )