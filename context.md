# sine-streamlit — session context

## What this is

A Streamlit app deployed on **CERN PaaS (OKD)** in project `sineplottest`.
Started as a sine-slider deploy test; pivoted to a **coffea object viewer** over a CERNBox public share. Current goal: boss-facing histogram browser for ttbarhad analysis outputs.

- **Local repo:** `/mnt/extra/wsLinux/apps/sine-streamlit`
- **GitHub:** https://github.com/mandalaritra1/sine-streamlit (public, ssh remote)
- **OKD project:** `sineplottest` (Developer perspective)
- **Deployment name:** `sine-streamlit` (created via Import from Git, Dockerfile strategy, Route on port 8080)

## Files in repo

- `app.py` — Streamlit viewer. Sidebar inputs a CERNBox share token, lists folder via WebDAV PROPFIND, downloads selected files, loads with `coffea.util.load` (falls back to `pickle.load`). It has three sample slots (`Signal`, `TTbar`, `QCD`) and looks for the Run-3 3D histogram `mtt_vs_dy_vs_chi` or any top-level `hist.Hist` with axes `ttbarmass`, `jetdy`, and `chi`. The main tabs support 1D overlays, `jetdy`/`chi` projections in contiguous `ttbarmass` slices, `ttbarmass` projections in contiguous `jetdy` or `chi` slices, per-axis rebin factors, strict custom-edge rebinning, sample scale factors, reduced-yield tables, and optional `Signal / (TTbar + QCD)` ratios.
- `requirements.txt` — streamlit, numpy, requests, matplotlib, mplhep, hist, coffea
- `Dockerfile` — `python:3.11-slim` + `build-essential` (for any non-wheel deps), pip install, `HOME=/app`, port 8080, XSRF/CORS off, group-0 writable for OKD's random UID
- `context.md` — this file

## Deployment recipe (already done, here for reference)

1. Edit code locally, `git push`.
2. In OKD: Topology → click ring → **Builds** tab → **Start build** (no webhook configured yet).
3. Build ~5–8 min on the scientific stack. Pod log should end with Streamlit "External URL: http://0.0.0.0:8080".
4. Topology ↗ arrow opens the Route.

## Known-good state

- Build **succeeded** with the latest commit (`0e807e5`).
- File ops to CERNBox public shares confirmed working from any host (no SSO):
  - List: `PROPFIND` on `https://cernbox.cern.ch/remote.php/dav/public-files/<token>/` with `Depth: 1`.
  - Download: `GET https://cernbox.cern.ch/remote.php/dav/public-files/<token>/<filename>`.
- Test share with `ZPrime4000_Local_2024.coffea` (62 KB) is `ou52Fa9fubKwN0M` — set as default in the sidebar.

## Why we ended up here (decision log)

- **Why Streamlit, not static HTML:** the eventual product is a coffea/hist browser; Streamlit fits naturally.
- **Why Dockerfile, not Python s2i:** Streamlit needs custom run flags (port 8080, `--server.address=0.0.0.0`, XSRF/CORS off for the OKD edge router); s2i's default `python app.py` doesn't fit.
- **Why CERNBox public share, not EOS mount:** EOS in PaaS pods needs an annotation + Kerberos keytab and the docs are SSO-walled. Public CERNBox share works without any auth or pod config — good enough for the histogram-browser milestone.

## OpenShift gotchas baked into the Dockerfile (do not strip)

- `chgrp -R 0 /app && chmod -R g=u /app` — OKD runs containers as a random non-root UID with GID 0. Without this, Streamlit can't write `~/.streamlit` and the pod CrashLoopBackOffs.
- `ENV HOME=/app` and `MPLCONFIGDIR=/app/.mpl` — keeps caches inside the writable dir.
- `STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false` and `_ENABLE_CORS=false` — the edge router otherwise breaks the websocket and the UI hangs on "Please wait…".

## Likely next steps (pick up here)

1. **Grow the viewer**:
   - Validate against real signal, TTbar, and QCD `.coffea` files that contain `mtt_vs_dy_vs_chi`.
   - Add category/systematic controls if the 3D histogram is later filled with extra axes.
   - Add a stacked `TTbar + QCD` background option under the signal overlay.
2. **Multi-file UX**: support loading files from more than one CERNBox share if signal/backgrounds live in separate shares.
3. **Switch to real EOS mount** when ready — CERN PaaS docs at https://paas.docs.cern.ch/3._Storage/eos/ (SSO-walled; user needs to paste the YAML/annotation snippets so we can wire a Deployment patch + Kerberos Secret).
4. **Webhook**: configure GitHub webhook so `git push` auto-rebuilds (currently manual via Topology → Start build).
5. **Image slimming**: drop `build-essential` if all deps actually have wheels for the pinned versions.

## Quick commands

```bash
# Local Streamlit dev
cd /mnt/extra/wsLinux/apps/sine-streamlit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py

# Local Docker test mimicking OKD's UID
docker build -t sine-streamlit .
docker run --rm -p 8080:8080 -u 12345:0 sine-streamlit

# Push update
git add -A && git commit -m "..." && git push
# then OKD: Topology → Builds → Start build
```

## Plan file

The original plan that approved this approach lives at `/home/aritra/.claude/plans/i-want-to-test-transient-naur.md`.
