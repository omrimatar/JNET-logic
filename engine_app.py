"""
engine_app.py — JNET Logic Compiler (Deterministic Engine, No API Key)
Same UI as app.py but calls the rule-based engine instead of Claude API.
"""

import io
import re
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.parser import parse_excel
from engine.compiler import compile_junction


def derive_junction_name(filename: str) -> str:
    stem = Path(filename).stem
    match = re.search(r"[A-Z]{2}\d{2}", stem)
    return match.group(0) if match else re.sub(r"[^\w]", "_", stem)


def rows_to_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    import csv
    writer = csv.DictWriter(
        output,
        fieldnames=['#', 'From', 'To', 'Template', 'JNET Logic Code'],
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


# ── UI ─────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="JNET Logic Engine", page_icon="🚦", layout="wide")
st.title("🚦 JNET Logic Engine (Deterministic)")
st.caption(
    "Upload a junction skeleton configuration → receive ready-to-use JNET priority logic as CSV. "
    "**No API key required.**"
)

with st.sidebar:
    st.header("⚙️ About")
    st.markdown(
        "This engine encodes all JNET V20.0 template rules directly in Python. "
        "Results are instant and deterministic."
    )
    st.divider()
    st.markdown("**Templates supported:** A B C D E F G")

uploaded_file = st.file_uploader(
    "Upload Skeleton Configuration",
    type=["xlsx"],
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
        """)
    st.stop()

junction_name = derive_junction_name(uploaded_file.name)
st.info(f"Junction: **{junction_name}** &nbsp;|&nbsp; File: `{uploaded_file.name}`")

# ── Preview ────────────────────────────────────────────────────────────────────
with st.expander("🔍 Preview input data"):
    try:
        cfg_preview = parse_excel(uploaded_file)
        uploaded_file.seek(0)
        st.subheader("General Info")
        st.write({
            "Vehicle Anchor": cfg_preview.vehicle_anchor,
            "LRT Anchor": cfg_preview.lrt_anchor,
            "Max Skeleton": cfg_preview.max_skeleton,
        })
        st.subheader("Stages Properties")
        st.dataframe(
            pd.DataFrame([vars(p) for p in cfg_preview.stage_props.values()]),
            use_container_width=True,
        )
        st.subheader("Inter-Stages")
        st.dataframe(
            pd.DataFrame([vars(t) for t in cfg_preview.transitions]),
            use_container_width=True,
        )
    except Exception as exc:
        st.error(f"Could not read file: {exc}")

# ── Compile ────────────────────────────────────────────────────────────────────
if st.button("🔧 Compile JNET Logic", type="primary", use_container_width=True):
    csv_filename = f"{junction_name}_JNET_Logic_Output.csv"

    try:
        uploaded_file.seek(0)
        cfg = parse_excel(uploaded_file)

        with st.spinner("Compiling…"):
            rows = compile_junction(cfg)

        df_result = pd.DataFrame(rows)

        st.divider()
        st.subheader(f"✅ Logic Table — {len(df_result)} transitions")
        st.dataframe(df_result, use_container_width=True)

        csv_text = rows_to_csv(rows)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ Download CSV",
                data=("\ufeff" + csv_text).encode("utf-8"),
                file_name=csv_filename,
                mime="text/csv",
                use_container_width=True,
            )

        st.success(f"Done — {len(rows)} rows compiled.")

        # ── Error rows ─────────────────────────────────────────────────────────
        error_rows = [r for r in rows if str(r['JNET Logic Code']).startswith('ERROR')]
        if error_rows:
            st.warning(f"{len(error_rows)} row(s) had errors:")
            for r in error_rows:
                st.code(f"Row {r['#']} ({r['From']}→{r['To']}): {r['JNET Logic Code']}")

    except ValueError as ve:
        st.error(f"Topology error: {ve}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        with st.expander("Full traceback"):
            st.exception(exc)
