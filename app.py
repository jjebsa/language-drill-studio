import asyncio
import base64
import csv
import io
import json
import os
import subprocess
import tempfile
import edge_tts
import pandas as pd
import streamlit as st
from deep_translator import GoogleTranslator
from supabase import Client, create_client

st.set_page_config(
    page_title="Spanish Audio Drill Generator", layout="centered"
)

st.title("🇪🇸 Spanish Listening Drill Studio")

# --- Supabase Initialization ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_DECKS = "decks"
BUCKET_AUDIO = "audio-cache"

# --- Session State Setup ---
if "current_pairs" not in st.session_state:
    st.session_state.current_pairs = None
if "selected_deck" not in st.session_state:
    st.session_state.selected_deck = None


# --- Supabase Storage Helpers ---
def list_deck_files():
    """Returns a sorted list of .csv files stored in the Supabase 'decks' bucket."""
    try:
        files = supabase.storage.from_(BUCKET_DECKS).list()
        csv_files = [
            f["name"]
            for f in files
            if f["name"].endswith(".csv") and f["name"] != "ping.txt"
        ]
        return sorted(csv_files)
    except Exception as e:
        st.error(f"Error fetching decks from Supabase: {e}")
        return []


def read_deck_file(filename: str) -> str:
    """Downloads a CSV deck from Supabase and returns text content."""
    data = supabase.storage.from_(BUCKET_DECKS).download(filename)
    return data.decode("utf-8-sig")


def save_deck_file(filename: str, content_bytes: bytes):
    """Uploads or updates a CSV deck in Supabase."""
    supabase.storage.from_(BUCKET_DECKS).upload(
        filename,
        content_bytes,
        file_options={"content-type": "text/csv", "upsert": "true"},
    )


def delete_deck_and_audio(filename: str):
    """Deletes deck CSV and its cached MP3 chunks from Supabase."""
    supabase.storage.from_(BUCKET_DECKS).remove([filename])

    deck_base = os.path.splitext(filename)[0]
    try:
        audio_files = supabase.storage.from_(BUCKET_AUDIO).list(deck_base)
        if audio_files:
            file_paths = [f"{deck_base}/{f['name']}" for f in audio_files]
            supabase.storage.from_(BUCKET_AUDIO).remove(file_paths)
    except Exception:
        pass


def parse_and_translate(content, filename=None):
    """Parses CSV content, preserves full sentences containing commas, translates single columns, and updates file."""
    translator = GoogleTranslator(source="es", target="en")
    pairs = []
    translations_added = False

    f_csv = io.StringIO(content.strip())
    reader = list(csv.reader(f_csv))

    if not reader:
        return pairs

    has_explicit_en_col = False
    start_idx = 0

    first_row = [field.strip().lower() for field in reader[0] if field.strip()]
    if first_row:
        if (
            len(first_row) >= 2
            and first_row[0] in ["spanish", "phrase", "text", "es"]
            and first_row[1] in ["english", "translation", "en"]
        ):
            has_explicit_en_col = True
            start_idx = 1
        elif len(first_row) == 1 and first_row[0] in [
            "spanish",
            "phrase",
            "text",
            "es",
        ]:
            start_idx = 1

    for row in reader[start_idx:]:
        clean_fields = [
            f.strip().strip('"').strip("'") for f in row if f.strip()
        ]
        if not clean_fields:
            continue

        if has_explicit_en_col and len(clean_fields) >= 2:
            es = clean_fields[0]
            en = clean_fields[1]
        else:
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

    if translations_added and filename:
        out_csv = io.StringIO()
        writer = csv.writer(out_csv)
        writer.writerow(["spanish", "english"])
        for es_text, en_text in pairs:
            writer.writerow([es_text, en_text])
        save_deck_file(filename, out_csv.getvalue().encode("utf-8"))

    return pairs


async def generate_phrase_chunks(phrases, deck_base, voice):
    """Generates TTS mp3 chunks and caches them in Supabase Storage."""
    existing_files = []
    try:
        listed = supabase.storage.from_(BUCKET_AUDIO).list(deck_base)
        existing_files = [f["name"] for f in listed]
    except Exception:
        pass

    for idx, text in enumerate(phrases):
        chunk_name = f"{idx}.mp3"
        supabase_path = f"{deck_base}/{chunk_name}"

        if chunk_name not in existing_files:
            communicate = edge_tts.Communicate(text, voice)
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".mp3"
            ) as tmp:
                await communicate.save(tmp.name)
                tmp.seek(0)
                audio_bytes = tmp.read()
                supabase.storage.from_(BUCKET_AUDIO).upload(
                    supabase_path,
                    audio_bytes,
                    file_options={
                        "content-type": "audio/mpeg",
                        "upsert": "true",
                    },
                )
            os.remove(tmp.name)


# --- Phrase Library Management ---
st.subheader("📚 Phrase Library")

tab_upload, tab_type = st.tabs(
    ["📁 Upload CSV File", "✍️️ Type / Paste Spanish Phrases"]
)

with tab_upload:
    uploaded_file = st.file_uploader(
        "Upload New Phrase CSV", type=["csv"], key="uploader"
    )
    if uploaded_file:
        file_name = uploaded_file.name
        raw_bytes = uploaded_file.getvalue()
        save_deck_file(file_name, raw_bytes)
        st.session_state.selected_deck = file_name
        st.toast(f"Saved '{file_name}' to Supabase library!", icon="💾")
        st.rerun()

with tab_type:
    deck_title = st.text_input(
        "Deck Name", placeholder="e.g., Local_Phrases", key="input_deck_name"
    )
    input_lang = st.radio(
        "Input Language:",
        ["Spanish", "English"],
        horizontal=True,
        key="input_lang_radio",
    )
    typed_phrases = st.text_area(
        f"Enter {input_lang} phrases (one per line):",
        height=140,
        placeholder=(
            "¿Dónde está el ayuntamiento?\nMe gustaría comprar un kilo de"
            " naranjas, por favor."
            if input_lang == "Spanish"
            else (
                "Where is the town hall?\nI would like to buy a kilo of"
                " oranges, please."
            )
        ),
        key="input_phrases",
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

            phrases_list = [
                p.strip() for p in typed_phrases.splitlines() if p.strip()
            ]

            with st.spinner("Translating and creating deck..."):
                out_csv = io.StringIO()
                writer = csv.writer(out_csv)

                if input_lang == "English":
                    translator = GoogleTranslator(source="en", target="es")
                    writer.writerow(["spanish", "english"])
                    for en_phrase in phrases_list:
                        try:
                            es_phrase = translator.translate(en_phrase)
                        except Exception:
                            es_phrase = en_phrase
                        writer.writerow([es_phrase, en_phrase])
                else:
                    writer.writerow(["spanish"])
                    for phrase in phrases_list:
                        writer.writerow([phrase])

                save_deck_file(clean_title, out_csv.getvalue().encode("utf-8"))

            st.session_state.selected_deck = clean_title
            st.toast(f"Created deck '{clean_title}'!", icon="🎉")
            st.rerun()

st.divider()

saved_files = list_deck_files()

if saved_files:
    col_select, col_delete = st.columns([3, 1])
    with col_select:
        selected_deck = st.selectbox(
            "Select a Phrase Deck:",
            saved_files,
            index=(
                saved_files.index(st.session_state.selected_deck)
                if st.session_state.selected_deck in saved_files
                else 0
            ),
            key="deck_selector",
        )
        st.session_state.selected_deck = selected_deck

    with col_delete:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        if st.button(
            "🗑️ Delete",
            type="secondary",
            use_container_width=True,
            key="btn_delete",
        ):
            delete_deck_and_audio(selected_deck)
            st.session_state.selected_deck = None
            st.session_state.current_pairs = None
            st.toast(f"Deleted '{selected_deck}'")
            st.rerun()

    raw_csv = read_deck_file(selected_deck)
    st.session_state.current_pairs = parse_and_translate(raw_csv, selected_deck)

else:
    st.info(
        "No CSV decks available. Upload a CSV file or type phrases above to"
        " get started."
    )

st.divider()

# --- Voice Selection & Generator ---
if st.session_state.current_pairs and st.session_state.selected_deck:
    deck_base = os.path.splitext(st.session_state.selected_deck)[0]

    voice = st.selectbox(
        "Voice Model",
        ["es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-ES-XimenaNeural"],
        key="voice_select",
    )

    spanish_phrases = [p[0] for p in st.session_state.current_pairs]

    if st.button(
        "🚀 Prepare / Rebuild Audio Chunks",
        use_container_width=True,
        key="btn_prep_audio",
    ):
        with st.spinner("Generating audio for sentences..."):
            try:
                listed = supabase.storage.from_(BUCKET_AUDIO).list(deck_base)
                if listed:
                    supabase.storage.from_(BUCKET_AUDIO).remove(
                        [f"{deck_base}/{f['name']}" for f in listed]
                    )
            except Exception:
                pass
            asyncio.run(
                generate_phrase_chunks(spanish_phrases, deck_base, voice)
            )
        st.toast("Audio prepared successfully!")
        st.rerun()

    # Verify chunk count
    cached_chunks = []
    try:
        cached_chunks = supabase.storage.from_(BUCKET_AUDIO).list(deck_base)
    except Exception:
        pass

    chunks_exist = len(cached_chunks) >= len(spanish_phrases)
    if not chunks_exist:
        with st.spinner("Preparing initial sentence audio..."):
            asyncio.run(
                generate_phrase_chunks(spanish_phrases, deck_base, voice)
            )
            chunks_exist = True

    # --- Synced Interactive Drill Player ---
    if chunks_exist:
        st.divider()
        st.subheader("🎧 Synced Practice Studio")

        audio_data_uris = []
        for i in range(len(spanish_phrases)):
            chunk_path = f"{deck_base}/{i}.mp3"
            try:
                chunk_bytes = supabase.storage.from_(BUCKET_AUDIO).download(
                    chunk_path
                )
                b64 = base64.b64encode(chunk_bytes).decode("utf-8")
                audio_data_uris.append(f"data:audio/mp3;base64,{b64}")
            except Exception:
                audio_data_uris.append("")

        deck_payload = json.dumps(
            [
                {"es": es, "en": en, "audio": uri}
                for (es, en), uri in zip(
                    st.session_state.current_pairs, audio_data_uris
                )
            ]
        )

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
                    <button class="btn" id="playPauseBtn">▶️️ Play Drill</button>
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

        st.components.v1.html(player_html, height=520)

        with st.expander(
            "📦 Optional: Stitch into Single MP3 File for Offline / Mobile Use"
        ):
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                export_speed = st.slider(
                    "Export Speed (%)", -40, 20, -15, step=5, key="exp_speed"
                )
                export_repeats = st.slider(
                    "Export Repeats", 1, 5, 2, key="exp_repeats"
                )
            with col_exp2:
                export_pause = st.slider(
                    "Export Pause (sec)",
                    1.0,
                    6.0,
                    3.0,
                    step=0.5,
                    key="exp_pause",
                )

            if st.button("Generate Combined MP3 File", key="btn_stitch_mp3"):
                with st.spinner(
                    "Stitching sentences, pauses, and adjusting audio tempo"
                    " with ffmpeg..."
                ):
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        silence_path = os.path.join(
                            tmp_dir, f"silence_{export_pause}s.mp3"
                        )
                        subprocess.run(
                            "ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t"
                            f' {export_pause} -c:a libmp3lame -y "{silence_path}"',
                            shell=True,
                            capture_output=True,
                        )

                        filelist = []
                        for idx in range(len(spanish_phrases)):
                            chunk_bytes = supabase.storage.from_(
                                BUCKET_AUDIO
                            ).download(f"{deck_base}/{idx}.mp3")
                            chunk_tmp_path = os.path.join(tmp_dir, f"{idx}.mp3")
                            with open(chunk_tmp_path, "wb") as f_chunk:
                                f_chunk.write(chunk_bytes)

                            for _ in range(export_repeats):
                                filelist.append(
                                    f"file '{os.path.abspath(chunk_tmp_path).replace('\\\\', '/')}'"
                                )
                                filelist.append(
                                    f"file '{os.path.abspath(silence_path).replace('\\\\', '/')}'"
                                )

                        manifest_path = os.path.join(tmp_dir, "manifest.txt")
                        with open(manifest_path, "w", encoding="utf-8") as f:
                            f.write("\n".join(filelist))

                        speed_factor = 1.0 + (export_speed / 100.0)
                        combined_tmp_path = os.path.join(
                            tmp_dir, f"{deck_base}_combined.mp3"
                        )

                        subprocess.run(
                            f'ffmpeg -f concat -safe 0 -i "{manifest_path}"'
                            f' -filter:a "atempo={speed_factor:.2f}" -c:a'
                            f' libmp3lame -q:a 2 -y "{combined_tmp_path}"',
                            shell=True,
                            capture_output=True,
                        )

                        with open(combined_tmp_path, "rb") as f_comb:
                            combined_bytes = f_comb.read()

                st.success("Single MP3 generated!")
                st.audio(combined_bytes, format="audio/mp3")
                st.download_button(
                    "📥 Download Combined MP3",
                    combined_bytes,
                    file_name=f"{deck_base}_drill.mp3",
                    mime="audio/mp3",
                    use_container_width=True,
                    key="dl_stitched",
                )
