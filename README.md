# TTbar Histogram Viewer

Small Streamlit app for browsing ttbar analysis `.coffea` outputs from a CERNBox public share.

The app expects files containing a 3D `hist.Hist` with axes:

- `ttbarmass`
- `jetdy`
- `chi`

It can compare Signal, TTbar, and QCD files, then plot:

- `jetdy` and `chi` projections in `ttbarmass` slices
- `ttbarmass` projections in `jetdy` or `chi` slices
- optional density normalization and ratios

## Quick Start

```bash
git clone https://github.com/mandalaritra1/sine-streamlit.git
cd sine-streamlit

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

streamlit run app.py
```

Then open the local URL printed by Streamlit, usually:

```text
http://localhost:8501
```

## How To Use

1. Paste the CERNBox public share token in the sidebar.
2. Select the Signal, TTbar, and QCD `.coffea` files.
3. Click **Load selected files**.
4. Use the tabs:
   - **Projection**: compare `jetdy` and `chi` in `ttbarmass` slices.
   - **Range slices**: compare `ttbarmass` in `jetdy` or `chi` slices.

The default public-share token currently points to Aritra's test share. If the file list looks stale, click **Refresh share**.

## Notes

This is intended to run locally for demos. The `.coffea` files can be memory-heavy, and small cloud containers may be OOM-killed while loading them.

If installation fails on an older Python version, use Python 3.11 or newer.
