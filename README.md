# YOLO OBB Portable

A lightweight companion to a full YOLO oriented-bounding-box (OBB) annotation tool. This app is
**ingest + annotate only** — no training, no inference, no pre-annotation. It exists so a
colleague can open a link, review or correct annotations (including ones a model pre-annotated
in the full app), and hand a project file back — without installing anything.

## What this app does

- **Import a project** (`.zip`) exported from the full app, or from this app itself, and review
  or correct its annotations.
- **Tile raw photos** you upload directly, using the same tiling parameters (size, overlap, crop
  %, padding mode) as the full app.
- **Draw and edit** oriented (or axis-aligned) boxes with the same drawing surface as the full
  app: a 3-click rotated-box gesture, drag/resize/rotate handles, right-click pan, wheel zoom,
  and an optional vegetation-index (ExGR) overlay to help spot plants against soil.
- **Export a project** (`.zip`) to hand back to the full app, or to someone else.

## What this app deliberately does not do

- **No training or inference.** Those stay in the full app; this is a review/correction surface.
- **No pre-annotation.** Model-generated (`unconfirmed`) boxes arrive already made, via an
  imported project file, for a human to confirm or fix here.
- **No orthomosaic support.** Only individual photos (JPG/PNG/TIFF) can be uploaded and tiled —
  multi-gigabyte orthomosaics aren't practical through a browser upload anyway. If you need to
  tile an orthomosaic, do it in the full app and share the resulting project file instead.
- **No page-level keyboard shortcuts** (tile navigation, number-key relabeling, confirm-tile).
  Streamlit's iframe boundary makes these unreliable, so this ships on-screen buttons instead —
  a deliberate v1 scope cut, not an oversight. (Delete/Backspace to remove a selected box *does*
  work, since that's handled inside the drawing canvas itself.)

## Nothing is saved server-side

Everything — uploaded photos, tiles, thumbnails, annotations — lives only in this browser
session's server-side memory (`st.session_state`), never on disk. Closing the tab or letting the
session go idle discards it.

**This means you must export before you're done.** No web app can guarantee synchronous cleanup
the instant a tab closes, and Streamlit reaps idle sessions on its own schedule, not instantly —
so "export before closing this tab" (shown as a persistent sidebar warning) is the only reliable
save path. Use **Clear session / start over** in the sidebar to wipe the current session's data
immediately, on demand, rather than waiting on that.

## Known deployment limits (Streamlit Community Cloud)

- Free-tier apps run on shared CPU with ~1GB RAM and **sleep after a period of inactivity** —
  the first load after a while can take anywhere from a few seconds to over a minute while the
  app wakes back up.
- File uploads are capped at 200MB/file (`.streamlit/config.toml`) — fine for individual drone
  photos, not for the orthomosaics this app doesn't support anyway.
- The deployed URL is public with no authentication. Each visitor's session is isolated by the
  platform (no shared/multi-tenant storage), which is sufficient for this app's scope, but don't
  put anything sensitive through it.
- For heavier or private use, self-host instead: `pip install -r requirements.txt && streamlit
  run streamlit_app.py`.

## Repo layout

```
streamlit_app.py              # entrypoint
app/                          # ported/portable business logic (tiling, manifest, annotations, session state)
components/obb_canvas/        # the drawing surface: a Streamlit custom component wrapping a small React/Konva bundle
  frontend/src/                 # component source
  build/                        # prebuilt static output - committed to git; Streamlit Cloud never runs `npm run build`
tests/                         # pytest suite (ported/adapted from the full app's tests where applicable)
```

If you edit anything under `components/obb_canvas/frontend/src/`, you must rebuild and commit
`components/obb_canvas/build/` (`cd components/obb_canvas/frontend && npm run build`) — Streamlit
Community Cloud serves that directory as static files as-is and never runs a JS build itself.

## Relationship to the full app

This is a companion, not a replacement. Project files exported from either app are interchangeable
with the other (same manifest/annotation schema, same zip layout) — that's the whole point:
pre-annotate and train in the full app, hand a project file here for review, export the reviewed
result back.
