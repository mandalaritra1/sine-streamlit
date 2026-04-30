import pickle
import re
import tempfile
from collections.abc import Mapping
from xml.etree import ElementTree as ET

import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import requests
import streamlit as st
from coffea.util import load as coffea_load
import hist

st.set_page_config(page_title="Coffea browser", layout="wide")
st.title("Coffea object browser")

DAV_BASE = "https://cernbox.cern.ch/remote.php/dav/public-files"


@st.cache_data(ttl=300, show_spinner="Listing share…")
def list_share(token: str):
    url = f"{DAV_BASE}/{token}/"
    r = requests.request("PROPFIND", url, headers={"Depth": "1"}, timeout=15)
    r.raise_for_status()
    ns = {"d": "DAV:"}
    root = ET.fromstring(r.content)
    items = []
    for resp in root.findall("d:response", ns):
        href = resp.find("d:href", ns).text or ""
        if href.rstrip("/").endswith(token):
            continue
        size_el = resp.find(".//d:getcontentlength", ns)
        size = int(size_el.text) if size_el is not None and size_el.text else 0
        name = href.rstrip("/").rsplit("/", 1)[-1]
        items.append((name, size))
    return items


@st.cache_data(ttl=600, show_spinner="Downloading and loading…")
def load_remote(token: str, filename: str):
    url = f"{DAV_BASE}/{token}/{filename}"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(r.content)
        path = f.name
    try:
        return coffea_load(path)
    except Exception:
        with open(path, "rb") as f:
            return pickle.load(f)


# ---------- sidebar: pick share + file ----------
with st.sidebar:
    st.header("Source")
    token = st.text_input("CERNBox share token", "ou52Fa9fubKwN0M")
    try:
        files = list_share(token)
    except Exception as e:
        st.error(f"PROPFIND failed: {e}")
        st.stop()
    if not files:
        st.warning("Empty share.")
        st.stop()
    labels = [f"{n}  ({s/1024:.1f} KB)" for n, s in files]
    pick = st.selectbox("File", labels)
    selected = files[labels.index(pick)][0]


obj = load_remote(token, selected)


# ---------- top-level summary ----------
def summarize(v):
    if isinstance(v, hist.Hist):
        axes = ", ".join(f"{a.name}({a.size})" for a in v.axes)
        return f"Hist[{axes}]"
    if isinstance(v, Mapping):
        return f"{type(v).__name__}(len={len(v)})"
    if hasattr(v, "shape"):
        try:
            return f"{type(v).__name__}{tuple(v.shape)}"
        except Exception:
            return type(v).__name__
    return type(v).__name__


st.subheader(f"`{selected}` — `{type(obj).__name__}`")

if isinstance(obj, Mapping):
    st.dataframe(
        [{"key": str(k), "type": type(v).__name__, "summary": summarize(v)} for k, v in obj.items()],
        use_container_width=True,
        hide_index=True,
    )
    key = st.selectbox("Inspect key", list(obj.keys()))
    item = obj[key]
else:
    item = obj
    key = "(root)"

st.markdown(f"### `{key}`  ·  `{type(item).__name__}`")


# ---------- hist.Hist renderer ----------
def is_discrete(ax):
    try:
        return bool(ax.traits.discrete)
    except Exception:
        return type(ax).__name__ in ("StrCategory", "IntCategory")


def render_hist(h: hist.Hist):
    st.write("**Axes**")
    st.table(
        [
            {
                "name": a.name,
                "label": getattr(a, "label", "") or "",
                "type": type(a).__name__,
                "size": a.size,
                "discrete": is_discrete(a),
            }
            for a in h.axes
        ]
    )

    st.write("**Per-axis controls** — `keep` keeps the axis as a plot dimension; `sum` integrates it; or pick a single category for discrete axes.")
    picks: dict = {}
    sums: list = []
    keeps: list = []
    for a in h.axes:
        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown(f"**{a.name}**")
        with col2:
            if is_discrete(a):
                cats = list(a)
                opts = ["<sum>", "<keep>"] + [str(c) for c in cats]
                choice = st.selectbox(f"axis_{a.name}", opts, index=0, key=f"sel_{a.name}", label_visibility="collapsed")
                if choice == "<sum>":
                    sums.append(a.name)
                elif choice == "<keep>":
                    keeps.append(a.name)
                else:
                    cat = cats[opts.index(choice) - 2]
                    picks[a.name] = cat
            else:
                choice = st.selectbox(f"axis_{a.name}", ["<keep>", "<sum>"], index=0, key=f"sel_{a.name}", label_visibility="collapsed")
                (keeps if choice == "<keep>" else sums).append(a.name)

    h2 = h[picks] if picks else h
    if keeps:
        h2 = h2.project(*keeps)
    elif sums:
        # everything was picked or summed — project to nothing remains
        h2 = h2.project()  # produces 0-D

    remaining = list(h2.axes) if hasattr(h2, "axes") else []
    st.write(f"**After reduction:** {len(remaining)}D  ·  shape={getattr(h2.values() if remaining else None, 'shape', None)}")

    if len(remaining) == 0:
        try:
            st.metric("integral", float(h2.values()))
        except Exception:
            st.write(h2)
    elif len(remaining) == 1:
        fig, ax = plt.subplots(figsize=(8, 4))
        try:
            hep.histplot(h2, ax=ax)
        except Exception:
            ax.stairs(h2.values(), h2.axes[0].edges)
        ax.set_xlabel(remaining[0].label or remaining[0].name)
        ax.set_ylabel("Counts")
        st.pyplot(fig, clear_figure=True)
    elif len(remaining) == 2:
        fig, ax = plt.subplots(figsize=(8, 6))
        try:
            h2.plot2d(ax=ax)
        except Exception:
            ax.imshow(h2.values().T, origin="lower", aspect="auto")
        ax.set_xlabel(remaining[0].label or remaining[0].name)
        ax.set_ylabel(remaining[1].label or remaining[1].name)
        st.pyplot(fig, clear_figure=True)
    else:
        st.warning(f"{len(remaining)}D not plotted; showing values shape.")
        st.write(h2.values().shape)


# ---------- dispatch ----------
if isinstance(item, hist.Hist):
    render_hist(item)
elif isinstance(item, Mapping):
    st.dataframe(
        [{"key": str(k), "type": type(v).__name__, "value": re.sub(r"\s+", " ", repr(v))[:300]} for k, v in item.items()],
        use_container_width=True,
        hide_index=True,
    )
elif isinstance(item, (list, tuple)):
    st.write(item[:200])
elif isinstance(item, np.ndarray):
    st.write(f"shape={item.shape}, dtype={item.dtype}")
    st.write(item)
else:
    st.code(repr(item)[:5000])
