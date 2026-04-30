from __future__ import annotations

import pickle
import re
import os
import gc
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import hist
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import requests
import streamlit as st
from coffea.util import load as coffea_load


DAV_BASE = "https://cernbox.cern.ch/remote.php/dav/public-files"
DEFAULT_TOKEN = "ou52Fa9fubKwN0M"
THREE_D_AXES = ("ttbarmass", "jetdy", "chi")
DEFAULT_HIST_KEY = "mtt_vs_dy_vs_chi"
SAMPLE_DEFAULTS = {
    "Signal": ("#bd1f01", 1.0),
    "TTbar": ("#3f90da", 1.0),
    "QCD": ("#ffa90e", 1.0),
}


@dataclass(frozen=True)
class Sample:
    role: str
    filename: str
    color: str
    scale: float
    hist_obj: hist.Hist
    summary: list[dict[str, str]]


st.set_page_config(page_title="TTbar histogram viewer", layout="wide")
plt.style.use(hep.style.CMS)
st.title("TTbar Histogram Viewer")


@st.cache_data(ttl=30, show_spinner="Listing CERNBox share...")
def list_share(token: str) -> list[tuple[str, int]]:
    url = f"{DAV_BASE}/{token}/"
    response = requests.request("PROPFIND", url, headers={"Depth": "1"}, timeout=15)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    ns = {"d": "DAV:"}
    items: list[tuple[str, int]] = []
    for item in root.findall("d:response", ns):
        href = item.find("d:href", ns)
        if href is None or not href.text:
            continue
        if href.text.rstrip("/").endswith(token):
            continue
        name = href.text.rstrip("/").rsplit("/", 1)[-1]
        size_el = item.find(".//d:getcontentlength", ns)
        size = int(size_el.text) if size_el is not None and size_el.text else 0
        if name.endswith((".coffea", ".pkl", ".pickle")):
            items.append((name, size))
    return sorted(items)


@st.cache_resource(ttl=600, show_spinner="Downloading and loading histogram...")
def load_remote_hist(token: str, filename: str, size: int) -> tuple[hist.Hist, list[dict[str, str]]]:
    del size
    url = f"{DAV_BASE}/{token}/{filename}"
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(response.content)
        path = handle.name

    try:
        output = coffea_load(path)
    except Exception:
        with open(path, "rb") as handle:
            output = pickle.load(handle)

    try:
        hist_obj = find_3d_hist(output)
        summary = summarize_output(output)
    finally:
        del output
        gc.collect()

    return hist_obj, summary


def main() -> None:
    with st.sidebar:
        st.header("Source")
        token = st.text_input("CERNBox share token", DEFAULT_TOKEN)
        if st.button("Refresh share", use_container_width=True):
            list_share.clear()
            load_remote_hist.clear()
            st.session_state["load_requested"] = False
        files = get_files_or_stop(token)
        samples = load_samples(token, files)

    if not samples:
        st.info("Choose files in the sidebar, then click **Load selected files**.")
        return

    render_summary(samples)
    render_viewer(samples)

    with st.expander("Loaded object summary", expanded=False):
        render_loaded_summary(samples)


def get_files_or_stop(token: str) -> list[tuple[str, int]]:
    try:
        files = list_share(token)
    except Exception as exc:
        st.error(f"CERNBox PROPFIND failed: {exc}")
        st.stop()
    if not files:
        st.warning("No `.coffea`, `.pkl`, or `.pickle` files found in this share.")
        st.stop()
    return files


def load_samples(token: str, files: list[tuple[str, int]]) -> list[Sample]:
    labels = ["<none>"] + [f"{name} ({size / 1024:.1f} KB)" for name, size in files]
    selected: list[tuple[str, str, str, float, int]] = []
    samples: list[Sample] = []

    for role, (default_color, default_scale) in SAMPLE_DEFAULTS.items():
        st.subheader(role)
        guessed_index = guess_file_index(role, files)
        default_index = guessed_index + 1 if guessed_index is not None else 0
        choice = st.selectbox("File", labels, index=default_index, key=f"file-{role}")
        color = st.color_picker("Color", default_color, key=f"color-{role}")
        scale = st.number_input("Scale", value=default_scale, step=0.1, format="%.6g", key=f"scale-{role}")
        if choice == "<none>":
            continue

        filename, size = files[labels.index(choice) - 1]
        selected.append((role, filename, color, float(scale), size))

    if not selected:
        st.session_state["load_requested"] = False
        return []

    st.caption(f"{len(selected)} file(s) selected. Loading starts only after clicking the button below.")
    if st.button("Load selected files", type="primary", use_container_width=True):
        st.session_state["load_requested"] = True
    if not st.session_state.get("load_requested", False):
        return []

    for role, filename, color, scale, size in selected:
        try:
            hist_obj, summary = load_remote_hist(token, filename, size)
        except Exception as exc:
            st.error(f"Could not load `{filename}` as a {', '.join(THREE_D_AXES)} histogram.")
            st.exception(exc)
            continue
        samples.append(Sample(role, filename, color, scale, hist_obj, summary))

    return samples


def guess_file_index(role: str, files: list[tuple[str, int]]) -> int | None:
    needle = role.lower()
    if role == "Signal":
        patterns = ("signal", "zprime", "rsgluon")
    elif role == "TTbar":
        patterns = ("ttbar", "ttto", "tt_")
    else:
        patterns = ("qcd",)

    for idx, (name, _) in enumerate(files):
        lowered = name.lower()
        if needle in lowered or any(pattern in lowered for pattern in patterns):
            return idx
    return None


def find_3d_hist(output: Any) -> hist.Hist:
    hists = find_histograms(output)
    if DEFAULT_HIST_KEY in hists and has_axes(hists[DEFAULT_HIST_KEY], THREE_D_AXES):
        return hists[DEFAULT_HIST_KEY]

    candidates = [hist_obj for hist_obj in hists.values() if has_axes(hist_obj, THREE_D_AXES)]
    if not candidates:
        found = ", ".join(f"{key}: {', '.join(axis_names(value))}" for key, value in hists.items())
        raise ValueError(f"No histogram has axes {THREE_D_AXES}. Found: {found or 'no hist.Hist objects'}")
    return candidates[0]


def summarize_output(output: Any) -> list[dict[str, str]]:
    if not isinstance(output, Mapping):
        return [{"key": "(root)", "type": type(output).__name__, "summary": summarize(output)}]
    rows = []
    for key, value in output.items():
        rows.append({"key": str(key), "type": type(value).__name__, "summary": summarize(value)})
    return rows


def render_summary(samples: list[Sample]) -> None:
    rows = []
    for sample in samples:
        rows.append(
            {
                "sample": sample.role,
                "file": sample.filename,
                "scale": sample.scale,
                "axes": ", ".join(axis_summary(axis) for axis in sample.hist_obj.axes),
                "raw yield": f"{safe_sum(sample.hist_obj):.6g}",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_viewer(samples: list[Sample]) -> None:
    reference = samples[0].hist_obj
    mtt_axis = axis_by_name(reference, "ttbarmass")
    mtt_edges = np.asarray(mtt_axis.edges, dtype=float)

    tabs = st.tabs(["Projection", "Range slices"])

    with tabs[0]:
        render_projection_slices(samples, reference)

    with tabs[1]:
        render_range_slices(samples, reference, mtt_edges)


def render_range_slices(samples: list[Sample], reference: hist.Hist, mtt_edges: np.ndarray) -> None:
    st.subheader("ttbarmass by chi/dy range")

    control_cols = st.columns([0.9, 1.5, 0.8, 0.8, 0.8])
    with control_cols[0]:
        slice_axis = st.radio("Slice axis", ["chi", "jetdy"], horizontal=False)
    with control_cols[1]:
        mtt_range = st.slider(
            "ttbarmass range",
            min_value=float(mtt_edges[0]),
            max_value=float(mtt_edges[-1]),
            value=(float(mtt_edges[0]), float(mtt_edges[-1])),
            step=float(np.min(np.diff(mtt_edges))),
            key="slice-mtt-range",
        )
    with control_cols[2]:
        n_ranges = st.selectbox("Slices", [1, 2, 3, 4], index=1, key="slice-count")
    with control_cols[3]:
        density = st.checkbox("Density", value=True, key="slice-density")
        show_ratio = st.checkbox("QCD + TTbar ratio", value=False, key="slice-ratio")
    with control_cols[4]:
        log_y = st.checkbox("Log y", value=False, key="slice-log-y")

    rebin_specs = rebin_controls(reference, key_prefix="slice")
    ranges = contiguous_range_controls(reference, slice_axis, int(n_ranges), key_prefix="slice")

    try:
        sliced_groups = [
            (
                label,
                [
                    (
                        sample,
                        prepare_hist(
                            sample.hist_obj,
                            sample.scale,
                            ["ttbarmass"],
                            mtt_range,
                            rebin_specs,
                            axis_ranges={slice_axis: axis_range},
                        ),
                    )
                    for sample in samples
                ],
            )
            for label, axis_range in ranges
        ]
    except Exception as exc:
        st.error("Could not reduce/rebin one of the range-sliced histograms.")
        st.exception(exc)
        return

    for row_start in range(0, len(sliced_groups), 2):
        cols = st.columns(2)
        for col, (label, projected) in zip(cols, sliced_groups[row_start : row_start + 2]):
            with col:
                st.markdown(f"#### {label}")
                render_1d(projected, "ttbarmass", density, log_y, show_ratio)


def render_projection_slices(samples: list[Sample], reference: hist.Hist) -> None:
    st.subheader("dy and chi by ttbarmass range")

    control_cols = st.columns([0.8, 0.8, 0.8, 1.2])
    with control_cols[0]:
        n_ranges = st.selectbox("Slices", [1, 2, 3, 4], index=1, key="projection-slice-count")
    with control_cols[1]:
        density = st.checkbox("Density", value=True, key="projection-density")
        show_ratio = st.checkbox("QCD + TTbar ratio", value=False, key="projection-ratio")
    with control_cols[2]:
        log_y = st.checkbox("Log y", value=False, key="projection-log-y")

    rebin_specs = rebin_controls(reference, key_prefix="projection")
    ranges = contiguous_range_controls(reference, "ttbarmass", int(n_ranges), key_prefix="projection")

    try:
        groups = [
            (
                label,
                [
                    (
                        sample,
                        prepare_hist(
                            sample.hist_obj,
                            sample.scale,
                            plot_axes=[axis_name],
                            mtt_range=axis_range,
                            rebin_specs=rebin_specs,
                        ),
                    )
                    for sample in samples
                ],
                axis_name,
            )
            for label, axis_range in ranges
            for axis_name in ("jetdy", "chi")
        ]
    except Exception as exc:
        st.error("Could not make the ttbarmass-sliced projections.")
        st.exception(exc)
        return

    for range_label, projected_dy, axis_name_dy in groups[0::2]:
        projected_chi = next_group(groups, range_label, "chi")
        cols = st.columns(2)
        with cols[0]:
            st.markdown(f"#### {axis_label(projected_dy[0][1], axis_name_dy)} | {range_label}")
            render_1d(projected_dy, axis_name_dy, density, log_y, show_ratio)
        with cols[1]:
            if projected_chi is not None:
                st.markdown(f"#### {axis_label(projected_chi[0][1], 'chi')} | {range_label}")
                render_1d(projected_chi, "chi", density, log_y, show_ratio)


def next_group(
    groups: list[tuple[str, list[tuple[Sample, hist.Hist]], str]],
    range_label: str,
    axis_name: str,
) -> list[tuple[Sample, hist.Hist]] | None:
    for label, projected, axis in groups:
        if label == range_label and axis == axis_name:
            return projected
    return None


def contiguous_range_controls(
    reference: hist.Hist,
    axis_name: str,
    n_ranges: int,
    key_prefix: str,
) -> list[tuple[str, tuple[float, float]]]:
    axis = axis_by_name(reference, axis_name)
    edges = np.asarray(axis.edges, dtype=float)
    edge_options = [float(edge) for edge in edges]

    st.markdown("##### Slice boundaries")
    if n_ranges == 1:
        low = edge_options[0]
        high = edge_options[-1]
        st.caption(f"{axis_name}: {low:g}-{high:g}")
        return [(f"{axis_name}: {low:g}-{high:g}", (low, high))]

    default_indices = np.linspace(0, len(edge_options) - 1, n_ranges + 1).round().astype(int)[1:-1]
    boundary_values = []
    cols = st.columns(min(3, n_ranges - 1))
    for idx, default_idx in enumerate(default_indices):
        with cols[idx % len(cols)]:
            value = st.select_slider(
                f"Boundary {idx + 1}",
                options=edge_options,
                value=edge_options[int(default_idx)],
                key=f"{key_prefix}-{axis_name}-boundary-{idx}",
            )
            boundary_values.append(float(value))

    boundaries = [edge_options[0], *sorted(set(boundary_values)), edge_options[-1]]
    if len(boundaries) != n_ranges + 1:
        st.warning("Duplicate boundaries collapsed one or more slices. Move the boundaries apart to restore all slices.")

    ranges: list[tuple[str, tuple[float, float]]] = []
    for low, high in zip(boundaries[:-1], boundaries[1:]):
        if low >= high:
            continue
        label = f"{axis_name}: {low:g}-{high:g}"
        ranges.append((label, (float(low), float(high))))

    st.caption(" | ".join(label for label, _ in ranges))
    return ranges


def rebin_controls(reference: hist.Hist, key_prefix: str) -> dict[str, int | np.ndarray]:
    specs: dict[str, int | np.ndarray] = {}
    with st.expander("Rebinning", expanded=True):
        st.caption("Custom edges must be existing bin edges of the loaded histograms.")
        cols = st.columns(3)
        for idx, axis_name in enumerate(THREE_D_AXES):
            axis = axis_by_name(reference, axis_name)
            with cols[idx]:
                mode = st.selectbox(
                    axis_name,
                    ["none", "factor", "custom edges"],
                    key=f"{key_prefix}-rebin-mode-{axis_name}",
                )
                if mode == "factor":
                    factor = st.number_input(
                        "Factor",
                        min_value=1,
                        max_value=max(1, axis.size),
                        value=2,
                        step=1,
                        key=f"{key_prefix}-rebin-factor-{axis_name}",
                    )
                    if factor > 1:
                        specs[axis_name] = int(factor)
                elif mode == "custom edges":
                    shown_edges = np.unique(
                        np.r_[np.asarray(axis.edges)[:: max(1, axis.size // 8)], np.asarray(axis.edges)[-1]]
                    )
                    default_edges = ", ".join(f"{edge:g}" for edge in shown_edges)
                    text = st.text_area(
                        "Edges",
                        value=default_edges,
                        key=f"{key_prefix}-rebin-edges-{axis_name}",
                        height=92,
                    )
                    edges = parse_edges(text)
                    if len(edges) >= 2:
                        specs[axis_name] = edges
    return specs


def prepare_hist(
    hist_obj: hist.Hist,
    scale: float,
    plot_axes: list[str],
    mtt_range: tuple[float, float],
    rebin_specs: dict[str, int | np.ndarray],
    axis_ranges: dict[str, tuple[float, float]] | None = None,
) -> hist.Hist:
    reduced = hist_obj

    for axis_name, spec in rebin_specs.items():
        reduced = rebin_hist(reduced, axis_name, spec)

    ranges = {"ttbarmass": mtt_range}
    if axis_ranges:
        ranges.update(axis_ranges)
    for axis_name, (low, high) in ranges.items():
        axis = axis_by_name(reduced, axis_name)
        if low > axis.edges[0] or high < axis.edges[-1]:
            reduced = reduced[{axis_name: slice(hist.loc(low), hist.loc(high))}]

    keep = [axis_name for axis_name in plot_axes if axis_name in axis_names(reduced)]
    reduced = reduced.project(*keep)
    if scale != 1.0:
        reduced = reduced * scale
    return reduced


def render_1d(
    projected: list[tuple[Sample, hist.Hist]],
    axis_name: str,
    density: bool,
    log_scale: bool,
    show_ratio: bool,
) -> None:
    if show_ratio:
        fig, (ax, rax) = plt.subplots(2, 1, figsize=(8.8, 6.2), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    else:
        fig, ax = plt.subplots(figsize=(8.8, 4.8))
        rax = None

    for sample, hist_obj in projected:
        values = np.asarray(hist_obj.values(), dtype=float)
        if density:
            total = values.sum()
            if total > 0:
                values = values / total
        hep.histplot(
            values,
            bins=axis_by_name(hist_obj, axis_name).edges,
            ax=ax,
            histtype="step",
            linewidth=1.6,
            color=sample.color,
            label=f"{sample.role} ({values.sum():.3g})",
        )

    ax.set_xlabel(axis_label(projected[0][1], axis_name) if rax is None else "", fontsize=17)
    ax.set_ylabel("Density" if density else "Events", fontsize=17, labelpad=8)
    ax.tick_params(axis="both", which="major", labelsize=14)
    ax.tick_params(axis="both", which="minor", labelsize=12)
    if log_scale:
        ax.set_yscale("log")
        ax.set_ylim(bottom=max(ax.get_ylim()[0], 1e-6 if density else 1e-3))
    ax.legend(fontsize=16, handlelength=1.5)

    if rax is not None:
        render_ratio(projected, axis_name, rax, density)
        rax.set_xlabel(axis_label(projected[0][1], axis_name), fontsize=17)

    fig.subplots_adjust(left=0.18, right=0.97, top=0.96, bottom=0.16 if rax is not None else 0.18, hspace=0.08)
    st.pyplot(fig, clear_figure=True)


def render_ratio(projected: list[tuple[Sample, hist.Hist]], axis_name: str, ax: Any, density: bool) -> None:
    by_role = {sample.role: hist_obj for sample, hist_obj in projected}
    if "Signal" not in by_role or not {"TTbar", "QCD"}.issubset(by_role):
        ax.text(0.5, 0.5, "Load Signal, TTbar, and QCD for ratio", ha="center", va="center", transform=ax.transAxes)
        return

    signal = np.asarray(by_role["Signal"].values(), dtype=float)
    background = np.asarray(by_role["TTbar"].values(), dtype=float) + np.asarray(by_role["QCD"].values(), dtype=float)
    if density:
        if signal.sum() > 0:
            signal = signal / signal.sum()
        if background.sum() > 0:
            background = background / background.sum()
    ratio = np.divide(signal, background, out=np.full_like(signal, np.nan), where=background != 0)
    edges = axis_by_name(by_role["Signal"], axis_name).edges
    ax.stairs(ratio, edges, color="black")
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=1.0)
    ax.set_ylabel("S/B", fontsize=16, labelpad=10)
    ax.tick_params(axis="both", which="major", labelsize=14)
    ax.tick_params(axis="both", which="minor", labelsize=12)
    ax.set_ylim(bottom=0)


def render_yields(projected: list[tuple[Sample, hist.Hist]]) -> None:
    st.subheader("Reduced Yields")
    rows = [
        {
            "sample": sample.role,
            "file": sample.filename,
            "yield": f"{safe_sum(hist_obj):.8g}",
            "nonzero bins": int(np.count_nonzero(hist_obj.values())),
        }
        for sample, hist_obj in projected
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_loaded_summary(samples: list[Sample]) -> None:
    for sample in samples:
        st.markdown(f"**{sample.role}: `{sample.filename}`**")
        st.dataframe(sample.summary, use_container_width=True, hide_index=True)


def rebin_hist(h: hist.Hist, axis_name: str, edges: int | np.ndarray) -> hist.Hist:
    if isinstance(edges, int):
        return h[{axis_name: hist.rebin(edges)}]

    edges = np.asarray(edges, dtype=float)
    axis = axis_by_name(h, axis_name)
    axis_idx = axis_names(h).index(axis_name)
    if not all(np.isclose(edge, axis.edges).any() for edge in edges):
        raise ValueError(
            f"Cannot rebin `{axis_name}` with incompatible edges. "
            f"Requested {edges.tolist()}, available edges span {axis.edges[0]:g} to {axis.edges[-1]:g}."
        )

    overflow = axis.traits.overflow or (edges[-1] < axis.edges[-1] and not np.isclose(edges[-1], axis.edges[-1]))
    underflow = axis.traits.underflow or (edges[0] > axis.edges[0] and not np.isclose(edges[0], axis.edges[0]))
    flow = overflow or underflow
    new_axis = hist.axis.Variable(edges, name=axis.name, label=axis.label, overflow=overflow, underflow=underflow)
    axes = list(h.axes)
    axes[axis_idx] = new_axis

    storage = storage_type(h)
    rebinned = hist.Hist(*axes, name=h.name, storage=storage)
    offset = 0.5 * np.min(axis.edges[1:] - axis.edges[:-1])
    edge_idx = axis.index(edges + offset)
    if edge_idx[-1] == axis.size + axis.traits.overflow:
        edge_idx = edge_idx[:-1]
    if underflow:
        if axis.traits.underflow:
            edge_idx += 1
        edge_idx = np.insert(edge_idx, 0, 0)

    take_count = new_axis.size + int(underflow) + int(overflow)
    rebinned.values(flow=flow)[...] = np.add.reduceat(h.values(flow=flow), edge_idx, axis=axis_idx).take(
        indices=range(take_count),
        axis=axis_idx,
    )
    if storage_type(rebinned) == hist.storage.Weight():
        rebinned.variances(flow=flow)[...] = np.add.reduceat(h.variances(flow=flow), edge_idx, axis=axis_idx).take(
            indices=range(take_count),
            axis=axis_idx,
        )
    return rebinned


def storage_type(hist_obj: hist.Hist) -> Any:
    if hasattr(hist_obj, "storage_type"):
        return hist_obj.storage_type()
    return hist_obj._storage_type()


def parse_edges(text: str) -> np.ndarray:
    values = [float(piece) for piece in re.split(r"[\s,]+", text.strip()) if piece]
    if len(values) < 2:
        return np.asarray([], dtype=float)
    edges = np.asarray(values, dtype=float)
    if np.any(np.diff(edges) <= 0):
        raise ValueError("Custom bin edges must be strictly increasing.")
    return edges


def find_histograms(output: Any) -> dict[str, hist.Hist]:
    if not isinstance(output, Mapping):
        return {}
    return {str(key): value for key, value in output.items() if isinstance(value, hist.Hist)}


def has_axes(hist_obj: hist.Hist, names: tuple[str, ...]) -> bool:
    available = set(axis_names(hist_obj))
    return all(name in available for name in names)


def axis_names(hist_obj: hist.Hist) -> list[str]:
    return [axis.name or f"axis_{idx}" for idx, axis in enumerate(hist_obj.axes)]


def axis_by_name(hist_obj: hist.Hist, axis_name: str) -> Any:
    for idx, axis in enumerate(hist_obj.axes):
        if (axis.name or f"axis_{idx}") == axis_name:
            return axis
    raise KeyError(axis_name)


def axis_label(hist_obj: hist.Hist, axis_name: str) -> str:
    axis = axis_by_name(hist_obj, axis_name)
    return axis.label or axis.name or axis_name


def axis_summary(axis: Any) -> str:
    name = axis.name or type(axis).__name__
    if hasattr(axis, "edges"):
        return f"{name}({axis.size}, {axis.edges[0]:g}-{axis.edges[-1]:g})"
    return f"{name}({axis.size})"


def summarize(value: Any) -> str:
    if isinstance(value, hist.Hist):
        return f"Hist[{', '.join(axis_summary(axis) for axis in value.axes)}]"
    if isinstance(value, Mapping):
        return f"{type(value).__name__}(len={len(value)})"
    if hasattr(value, "shape"):
        return f"{type(value).__name__}{tuple(value.shape)}"
    return type(value).__name__


def safe_sum(hist_obj: hist.Hist) -> float:
    try:
        return float(np.nansum(hist_obj.values()))
    except Exception:
        return float("nan")


if __name__ == "__main__":
    main()
