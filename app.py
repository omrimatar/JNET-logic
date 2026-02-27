"""
JNET Logic Compiler — Streamlit Web App
Reads a skeleton configuration Excel file, calls Claude API with
the jnet-logic skill instructions, and returns a downloadable CSV.
"""

import io
import csv
import re
from pathlib import Path

import streamlit as st
import anthropic
import pandas as pd

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
SKILL_PATH = Path(__file__).parent / ".claude" / "commands" / "jnet-logic.md"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_system_prompt() -> str:
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        return f.read()


def parse_excel(file) -> dict[str, pd.DataFrame]:
    xl = pd.ExcelFile(file)
    sheets = {}
    for name in ["General Info", "Inter-Stages", "Stages Properties"]:
        if name in xl.sheet_names:
            sheets[name] = xl.parse(name)
    return sheets


def parse_csv_input(file) -> dict[str, pd.DataFrame]:
    """
    For CSV input: a single CSV that contains all three sections
    separated by a blank line, OR just Inter-Stages data.
    Falls back to treating the whole file as Inter-Stages.
    """
    content = file.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(content))
    return {"Inter-Stages": df}


def format_prompt(sheets: dict[str, pd.DataFrame]) -> str:
    lines = [
        "Compile the JNET logic for the junction below.",
        "Return ONLY raw CSV data — no markdown, no explanation, no code blocks.",
        "First line must be exactly: #,From,To,Template,JNET Logic Code",
        "Each logic code cell that contains commas must be wrapped in double quotes.",
        "",
    ]

    if "General Info" in sheets:
        lines.append("=== GENERAL INFO ===")
        for _, row in sheets["General Info"].dropna(how="all").iterrows():
            vals = [str(v) for v in row if pd.notna(v)]
            lines.append(", ".join(vals))
        lines.append("")

    if "Stages Properties" in sheets:
        lines.append("=== STAGES PROPERTIES ===")
        lines.append(sheets["Stages Properties"].dropna(how="all").to_string(index=False))
        lines.append("")

    if "Inter-Stages" in sheets:
        lines.append("=== INTER-STAGES (row numbers match the source file) ===")
        df = sheets["Inter-Stages"].dropna(how="all")
        for i, row in df.iterrows():
            vals = [str(v) if pd.notna(v) else "" for v in row]
            lines.append(f"Row {i + 1}: {', '.join(vals)}")
        lines.append("")

    return "\n".join(lines)


def call_claude(system_prompt: str, user_message: str, api_key: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},   # cache the large system prompt
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def stream_claude(system_prompt: str, user_message: str, api_key: str, model: str):
    """Yield text chunks for Streamlit's write_stream."""
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def clean_csv_text(raw: str) -> str:
    """Strip markdown fences, leading/trailing whitespace, etc."""
    text = raw.strip()
    # Remove ```csv ... ``` or ``` ... ```
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def csv_to_dataframe(csv_text: str) -> pd.DataFrame:
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=rows[0])


def derive_junction_name(filename: str) -> str:
    stem = Path(filename).stem
    match = re.search(r"[A-Z]{2}\d{2}", stem)
    return match.group(0) if match else re.sub(r"[^\w]", "_", stem)


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────

st.set_page_config(page_title="JNET Logic Compiler", page_icon="🚦", layout="wide")
st.title("🚦 JNET Logic Compiler")
st.caption("Upload a junction skeleton configuration → receive ready-to-use JNET priority logic as CSV.")

# ── Sidebar ──────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("Anthropic API Key", type="password",
                            help="Your key. All usage is billed to this key.")
    model = st.selectbox(
        "Model",
        ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        help="Sonnet is the best balance of quality and cost (~$0.35/run).",
    )
    use_streaming = st.toggle("Stream output", value=True,
                               help="Show output as it is generated.")
    st.divider()
    st.markdown("**Estimated cost per run**")
    st.markdown("- Sonnet: ~$0.10–0.20 (with prompt caching)")
    st.markdown("- Opus: ~$0.80–1.50")
    st.markdown("- Haiku: ~$0.02–0.05")
    st.divider()
    st.markdown("Skill file: `.claude/commands/jnet-logic.md`")
    if SKILL_PATH.exists():
        st.success("Skill file found ✓")
    else:
        st.error("Skill file not found! Run from the project folder.")

# ── Main content ─────────────────────────────
uploaded_file = st.file_uploader(
    "Upload Skeleton Configuration",
    type=["xlsx", "csv"],
    help="Excel file with sheets: General Info, Inter-Stages, Stages Properties",
)

if not uploaded_file:
    with st.expander("📋 Required file format", expanded=True):
        st.markdown("""
**Excel file (.xlsx) with 3 sheets:**

| Sheet | Required columns |
|:------|:----------------|
| General Info | Parameter, Value (Vehicle Anchor, LRT Anchor, Maximum Skeleton) |
| Stages Properties | Stage, Minimum Type, Detectors, Waterfall Level, Sibling Priority |
| Inter-Stages | From Stage, To Stage, Rest of Skeleton |

**CSV input** is also accepted for Inter-Stages-only files.
        """)
    st.stop()

# ── File loaded ──────────────────────────────
junction_name = derive_junction_name(uploaded_file.name)
st.info(f"Junction: **{junction_name}** &nbsp;|&nbsp; File: `{uploaded_file.name}`")

# Preview
with st.expander("🔍 Preview input data"):
    try:
        if uploaded_file.name.endswith(".xlsx"):
            sheets_preview = parse_excel(uploaded_file)
            uploaded_file.seek(0)
        else:
            sheets_preview = parse_csv_input(uploaded_file)
            uploaded_file.seek(0)

        for name, df in sheets_preview.items():
            st.subheader(name)
            st.dataframe(df.dropna(how="all"), use_container_width=True)
    except Exception as exc:
        st.error(f"Could not read file: {exc}")

if not api_key:
    st.warning("Enter your Anthropic API key in the sidebar to continue.")
    st.stop()

if not SKILL_PATH.exists():
    st.error(f"Skill file not found at `{SKILL_PATH}`. Run the app from the project folder.")
    st.stop()

# ── Compile button ────────────────────────────
if st.button("🔧 Compile JNET Logic", type="primary", use_container_width=True):

    csv_filename = f"{junction_name}_JNET_Logic_Output.csv"
    raw_text = ""

    try:
        with st.spinner("Loading skill instructions…"):
            system_prompt = load_system_prompt()

        with st.spinner("Parsing skeleton file…"):
            uploaded_file.seek(0)
            if uploaded_file.name.endswith(".xlsx"):
                sheets = parse_excel(uploaded_file)
            else:
                sheets = parse_csv_input(uploaded_file)
            user_message = format_prompt(sheets)

        st.divider()
        st.subheader("📤 Raw API Output")

        if use_streaming:
            # Stream into a text area and collect full text
            collected = []
            output_placeholder = st.empty()

            with st.spinner("Compiling… (streaming)"):
                for chunk in stream_claude(system_prompt, user_message, api_key, model):
                    collected.append(chunk)
                    output_placeholder.text_area(
                        "Live output", "".join(collected), height=300, label_visibility="collapsed"
                    )
            raw_text = "".join(collected)
            output_placeholder.text_area(
                "Raw output", raw_text, height=300, label_visibility="collapsed"
            )
        else:
            with st.spinner("Compiling… (this may take 30–60 s)"):
                raw_text = call_claude(system_prompt, user_message, api_key, model)
            st.text_area("Raw output", raw_text, height=300, label_visibility="collapsed")

        # Parse CSV
        csv_text = clean_csv_text(raw_text)
        df_result = csv_to_dataframe(csv_text)

        st.divider()
        st.subheader(f"✅ Logic Table — {len(df_result)} transitions")
        st.dataframe(df_result, use_container_width=True)

        # Download buttons
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ Download CSV",
                data=("\ufeff" + csv_text).encode("utf-8"),   # UTF-8 BOM for Excel
                file_name=csv_filename,
                mime="text/csv",
                use_container_width=True,
            )
        with col2:
            st.download_button(
                "⬇️ Download Raw Response",
                data=raw_text.encode("utf-8"),
                file_name=f"{junction_name}_raw_response.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.success(f"Saved as `{csv_filename}` — click the button above to download.")

    except anthropic.AuthenticationError:
        st.error("Invalid API key. Check your key in the sidebar.")
    except anthropic.RateLimitError:
        st.error("Rate limit hit. Wait a moment and try again.")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        with st.expander("Full traceback"):
            st.exception(exc)
