import os
from pathlib import Path

import numpy as np
import streamlit as st

st.title("Sine playground + EOS file probe")

# --- Sine demo (kept from v1) ---
with st.expander("Sine playground", expanded=False):
    f = st.slider("frequency", 0.1, 5.0, 1.0, 0.1)
    A = st.slider("amplitude", 0.1, 5.0, 1.0, 0.1)
    x = np.linspace(0, 10, 500)
    st.line_chart({"y": A * np.sin(f * x)})

# --- EOS file probe ---
st.header("EOS file probe")

default_path = os.environ.get(
    "EOS_PATH", "/eos/user/a/amandal/ttbarhad_root_files"
)
path_str = st.text_input("Directory to list", default_path)
path = Path(path_str)

st.write(f"**Probing:** `{path}`")

# Diagnostics that help diagnose mount issues
st.write("**Exists?**", path.exists())
st.write("**Is dir?**", path.is_dir())

# Show what /eos itself looks like, if anything
eos_root = Path("/eos")
st.write(f"**`/eos` exists?** {eos_root.exists()} — listing (top 20):")
if eos_root.exists():
    try:
        st.write(sorted(p.name for p in eos_root.iterdir())[:20])
    except Exception as e:
        st.error(f"Cannot list /eos: {e!r}")
else:
    st.info("`/eos` is not mounted in this pod. EOS injection is required on CERN PaaS.")

# Try the actual target
st.subheader("Target listing")
try:
    entries = sorted(path.iterdir())
    st.success(f"Found {len(entries)} entries.")
    rows = [
        {
            "name": p.name,
            "size_MB": (p.stat().st_size / 1e6) if p.is_file() else None,
            "is_dir": p.is_dir(),
        }
        for p in entries
    ]
    st.dataframe(rows, use_container_width=True)
except Exception as e:
    st.error(f"Listing failed: {type(e).__name__}: {e}")
