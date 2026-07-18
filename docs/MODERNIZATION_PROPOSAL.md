# Stytra Modernization — Architecture Proposal

Status: **Phase 1 (Python 3.12 port) complete.** Also shipped outside the original phase list: a ScanImage acquisition trigger via the MATLAB Engine API (`stytra/hardware/scanimage.py`).

**Phase 2, part A (camera detection + IDS backend) complete** — see [../.claude/plans/starry-wondering-wirth.md](../.claude/plans/starry-wondering-wirth.md) for the executed plan. `Camera.list_devices()` added to the base class plus OpenCV/Basler/IDS backends, a new full `IdsCamera` backend (`stytra/hardware/video/cameras/ids.py`, untested against real hardware), and a cross-vendor `detect_cameras()` helper.

**Phase 3a (multi-camera acquisition & tracking architecture) complete.** `CameraVisualExperiment`/`TrackingExperiment` (`stytra/experiments/tracking_experiments.py`) now run any number of cameras concurrently, each with its own independent tracking pipeline and optional recording, via a new `cameras=[...]` list config. The legacy singular `camera=`/`tracking=`/`recording=` config is fully preserved (normalized internally into a one-entry list) — every existing example script and test needed zero changes. Read-only backward-compat properties (`.camera`, `.pipeline`, `.frame_dispatcher`, `.acc_tracking`, etc., all resolving to "the first camera") keep every GUI/save-path file that hasn't been updated yet working unchanged. New `stytra/tests/test_multi_camera.py` runs two `VideoFileSource` cameras with different tracking methods (tail + eyes) concurrently end-to-end. Not yet done: real dual-hardware-camera validation (needs your rig).

**Phase 4 (heart-rate & pectoral-fin tracking) complete** — the actual motivating feature for this whole modernization. Two new tracking methods (`stytra/tracking/heart.py`, `stytra/tracking/fin.py`), each a rectangular-ROI `ImageToDataNode` following the exact same contract as `tail.py`/`eyes.py`: heart rate from ROI mean-intensity oscillation (numba-jitted detrend + peak-detection → BPM), fin angle from a closed-form 2×2 PCA on the thresholded ROI mask. Both designed from scratch and validated against synthetic ground truth (no real footage available here) — heart rate recovered 181 BPM vs. a true 180 BPM signal, fin angle recovered within ~0.2° across 5 test angles (mod the intrinsic 180° PCA-axis ambiguity). New ROI selection widgets (`HeartRateSelection`/`PectoralFinSelection` in `camera_display.py`, sharing one small generic base class rather than duplicating `EyeTrackingSelection`'s ROI-wiring code) and two new `pipeline_dict` entries (`heart_rate`, `pectoral_fin`) — since Phase 3a already made tracking per-camera, these plug in immediately: `cameras=[dict(role="heart_cam", tracking=dict(method="heart_rate"), ...), dict(role="tail_cam", tracking=dict(method="tail"), ...)]` runs both concurrently with zero other changes, confirmed by a new integration test. Not yet done: validation against real embedded-fish heart/fin footage, and real ROI-widget GUI interaction (needs your rig).

**Phase 3b (tiled multi-camera GUI + Camera Setup dialog) complete.** `CameraExperimentWindow`/`TrackingExperimentWindow` (`stytra/gui/container_windows.py`) now build one preview dock per camera role (objectName `"dock_camera_<role>"`) instead of a single fixed one, each showing that specific camera's `display_overlay` widget (e.g. its own `HeartRateSelection`/`TailTrackingSelection`), with its own diagnostics dropdown and tracking-params button. `CameraViewWidget`/`CameraSelection` (`stytra/gui/camera_display.py`) gained an optional `role=` constructor param to target a specific camera - omitted, behavior is unchanged, which is how every existing single-camera experiment keeps working with zero modification. New `stytra/gui/camera_setup_dialog.py`'s `CameraSetupDialog` uses Phase 2's `detect_cameras()` to list connected devices and lets you check which to use, assign each a role and (optionally) a tracking method, and hands back a `cameras=[...]` list in exactly the shape Phase 3a expects - deliberately doesn't launch an experiment itself (that needs a real, user-supplied `Protocol`) or live-preview cameras during setup (the tiled window built above already *is* the live preview, immediately after picking). Verified: two-camera tiling produces correctly-bound, distinctly-named docks (not both accidentally pointing at the same camera); single-camera experiments are provably unaffected. Not yet done: real interactive use (dragging/resizing tiles, running the setup dialog against real detected hardware) - needs your rig.

**Phase 5 (Zarr video writer) complete.** New `ZarrVideoWriter` (`stytra/hardware/video/write.py`) follows the exact same `VideoWriter` contract as `H5VideoWriter`/`StreamingVideoWriter` - streaming, chunked (`chunk_frames=32` default), blosc/zstd-compressed writes instead of `H5VideoWriter`'s buffer-everything-in-RAM-then-write-once approach, selectable per-camera via `recording=dict(extension="zarr")` with zero other config changes (wired into `TrackingExperiment._setup_recording`). Guarded `import zarr`; confirmed against the real installed `zarr==3.2.1` v3 API (`zarr.open_group`, `create_array(..., compressors=[BloscCodec(...)])`, per-frame `resize`+assign, `.attrs`). `zarr>=3.0` added to `setup.py`/`environment.yml`. Tested via `stytra/tests/test_zarr_writer.py`: direct `_configure`/`_ingest_frame`/`_complete` unit tests (including the async-filename fallback-then-rename path), plus one integration test recording through a full `TrackingExperiment` run.

Also found and fixed a real, pre-existing bug while building this: `H5VideoWriter._complete` did `filename + "video.hdf5"` where `filename` is a `PosixPath`, not `str` (crashes on any real recording - trivial one-line fix, now matches `StreamingVideoWriter`'s existing `str(filename)` pattern). Also found (but did **not** fix - flagged as a separate follow-up task) two deeper, pre-existing bugs in the shared recording-shutdown path, both reproducing identically with `H5VideoWriter`/`StreamingVideoWriter` and unrelated to `ZarrVideoWriter` specifically: (1) `Experiment.wrap_up()` is not re-entrant - it ends with `self.app.closeAllWindows()`, which re-enters `wrap_up()` via `closeEvent()`, and `frame_recorders` are never told to stop on that path; (2) a `TrackingProcess` dispatcher constructed with a `recording_signal` (i.e. a live `frame_copy_queue`) can fail to report as exited even after its `run()` method returns cleanly (isolated via print-instrumentation to *something* in the child's post-`run()` `multiprocessing` epilogue, not yet root-caused). `test_zarr_writer.py`'s integration test works around both via bounded `join(timeout=...)` + `terminate()` fallback rather than a real `wrap_up()` call.

**Phase 6 (stimulus/perf/GUI polish) complete - final phase of this roadmap.** A targeted research pass (not a vague cleanup) across stimulus rendering, hardware/software communication latency, and GUI usability found seven concrete items, implemented and tested:

- Two real, previously-unflagged bugs: `ExperimentWindow.change_folder_gui` (`stytra/gui/container_windows.py`) treated a canceled `QFileDialog` (which returns `""`, not `None`) as a valid folder, silently blanking `experiment.base_dir`; `CalibratedCircleStimulus.paint` (`stytra/stimulation/stimuli/visual.py`) had a stray `print(mm_px)` firing every single paint call. Both fixed; a matching stray `print(folder)` removed alongside the first.
- Two stimulus-rendering perf fixes, both changing only *when* work happens, not *what* gets drawn (verified pixel-identical output against the old uncached computation): `VideoStimulus.paint` now caches its `qimage2ndarray` conversion, only rebuilding it when `update()` actually advances to a new video frame rather than on every paint call; `RadialSineStimulus.paint` now caches the phase-independent sqrt-distance field (only `(w, h, mm_px, period)`-dependent), leaving just the cheap `sin(...)` as per-frame work.
- Three GUI usability additions: `ExperimentWindow.closeEvent` now prompts for confirmation (`QMessageBox.question`) before wrapping up if a protocol is still running, instead of silently tearing everything down; `StatusMessageDisplay` now also routes `W:`/`E:`-prefixed messages through `experiment.logger` (optional `logger=` param) so they land in the persistent log dock/file instead of only the 3-second-fading status bar; `CameraSetupDialog` gained "Save config"/"Load config" buttons to persist and restore role/tracking-method selections by `(backend, device_id)` across sessions.

Explicitly scoped out as disproportionate for a "polish" phase (documented in the approved plan, not silently dropped): a vsync/`frameSwapped`-based stimulus timing overhaul (large, needs a real display + photodiode to verify), tightening the tracking/dispatch poll-loop timeouts (real hot loop, risk outweighs payoff at this stage), and precomputing `HighResWindmillStimulus` geometry.

Tested via `stytra/tests/test_phase6_polish.py` (14 tests: cancel/accept folder dialog, closeEvent confirmation guard across all three states, status-message logger routing, camera-config save/load round-trip including "device no longer connected" skip behavior, and pixel-exact caching correctness for both stimuli) plus the full existing suite - all pass. One pre-existing, environment-specific issue reconfirmed (not caused by this phase): running many real-Qt-window tests sequentially in one process on this macOS dev machine eventually destabilizes interpreter teardown (previously an outright segfault in `test_examples.py`/`test_init_gui.py`; with those two excluded, now a very slow/hanging `pytest`-session teardown after every individual test has already reported passed) - absent on the real Linux CI (`pytest --forked`), and every test's own result is unaffected by it.

**Modernization roadmap complete** (Phases 1-6). Real-hardware verification (vendor cameras, MATLAB/ScanImage, real embedded-fish heart/fin footage, real projector timing, long-recording memory profiling) remains outstanding throughout, as flagged in each phase above - this all needs your rig.

## 0. Current state (as-is)

- **Packaging**: `setup.py` classifiers claim Python 3.6/3.7; `tox.ini` actually tests 3.6–3.8; Python 3.9 support was added in a later commit without updating classifiers. No `pyproject.toml`, no pinned `requirements.txt`.
- **Camera backends** (`stytra/hardware/video/cameras/`): `ximea.py`, `avt.py` (wraps `pymba`/Vimba), `basler.py` (wraps `pypylon`), `spinnaker.py` (wraps `PySpin`), `mikrotron.py` (raw `ctypes` frame grabber), `opencv.py` (generic UVC/webcam). Selected via a string key in experiment config (`camera_class_dict` in `cameras/__init__.py`). No cross-vendor auto-detection — only `AvtCamera` enumerates same-vendor devices.
- **Tracking** (`stytra/tracking/`): DAG pipeline framework (`pipelines.py`, built on `anytree`) with tail (`tail.py`, numba-jitted), eye (`eyes.py`), and multi-fish (`fish.py`) tracking. No heart-rate or pectoral-fin tracking today.
- **ROI selection**: `stytra/gui/camera_display.py` already has a live preview + draggable ROI overlay pattern (`CameraSelection`, `EyeTrackingSelection`, etc.) using `pyqtgraph` ROI widgets.
- **Stimulus display**: `stytra/stimulation/stimulus_display.py`, `QPainter`-based 2D drawing onto a `QOpenGLWidget` surface positioned on a second monitor (`gui/monitor_control.py`).
- **Multiprocessing/IPC**: one `CameraSource` process → `arrayqueues` shared-memory queue → one `TrackingProcess` → queue → GUI/`VideoWriter` process. Single camera per experiment only. `arrayqueues` was recently bumped "to prevent Process crash" (known stability history).
- **Storage**: config/metadata via `flammkuchen` (HDF5/PyTables); video via `H5VideoWriter` (buffers the **entire** video in a Python list in RAM before one `fl.save` call) or `StreamingVideoWriter` (PyAV → mp4). No Zarr usage anywhere.
- **GUI**: PyQt5 throughout; parameter editing via `lightparam` (portugueslab package).

## 1. Dependency audit — what's actually "the lab's" vs. vendor hardware SDKs

Your question conflated two different categories. Worth separating them because they need different strategies:

| Package | What it is | Python 3.12 status | Recommendation |
|---|---|---|---|
| `arrayqueues` | Portugueslab shared-memory queue (~200 lines) | Small/unmaintained, crash history noted in your own commit log | **Replace** with a small in-house ring buffer on `multiprocessing.shared_memory` (stdlib). Removes the dependency and gives us control over the exact bug class that bit you before. |
| `lightparam` | Portugueslab parameter-tree/GUI framework, used everywhere for live camera/tracking params | Maintained, pure Python, no obvious 3.12 blockers | **Keep.** Rewriting this is high risk / low reward — it's load-bearing across the whole GUI. |
| `flammkuchen` | Thin HDF5 (PyTables) wrapper | Maintained, pure Python | **Keep** for config/metadata. Only the *image* data path moves to Zarr per your request. |
| `pyFirmata` | Arduino serial protocol, last released 2015, uses APIs removed in Python ≥3.11 | **Broken on 3.12** | **Replace** with `pyfirmata2` (maintained fork, drop-in-ish API). |
| `qdarkstyle`, `anytree`, `pims`, `colorspacious`, etc. | Standard PyPI, maintained | Fine | Keep, bump version pins. |
| `PySpin` (FLIR Spinnaker), `pymba`/Vimba (AVT), Ximea `xiapi` | **Proprietary vendor SDKs**, bundled with the manufacturer's own installer, not real PyPI packages | N/A — not ours to replace | **Cannot substitute these.** They're closed bindings to physical camera drivers. Best we can do: keep these imports fully optional/lazy (already mostly true), document exact install steps per vendor, and make the app degrade gracefully (skip a vendor backend entirely) when the SDK isn't present. If you have access to vendor-provided Python 3.12 wheels, we use those; otherwise that specific backend is simply unavailable until the vendor ships one. |

So: for the "other software dependencies" question — the portugueslab packages (`arrayqueues`, `pyFirmata`→`pyfirmata2`) we can and will replace with standard/stdlib equivalents. The camera vendor SDKs are a separate matter entirely and aren't things any port can work around; only the vendor can provide a 3.12-compatible build.

`PyQt5` itself is not a blocker — current PyQt5 wheels (≥5.15.9) support Python 3.12, so no forced migration to PySide6/PyQt6. Not in scope unless you want it for other reasons (licensing, long-term support).

## 2. Camera auto-detection & multi-camera architecture

**New `CameraManager`**: each backend module gains a static `list_devices()` that returns `(vendor, serial, model)` tuples, wrapped in a try/except so a vendor with no SDK installed is silently skipped. `CameraManager.detect_all()` merges results across all installed backends into one list, independent of vendor.

**New "Camera Setup" screen** (replaces having to hand-edit config to name a camera): shows a grid of live thumbnail previews for every detected camera, lets you assign each one a role (e.g. "tail cam", "heart/fin cam") and draw its ROI(s) inline — reusing the existing `CameraSelection`/`EyeTrackingSelection` ROI-overlay pattern in `camera_display.py` rather than inventing a new widget system.

**Multi-camera acquisition**: today exactly one `CameraSource` + one `TrackingProcess` is hardcoded per experiment. This becomes a list: one `CameraSource` process and one `TrackingProcess` (running whatever pipeline that camera's role needs) per configured camera, all spawned from experiment config. A shared monotonic clock reference is broadcast at experiment start so frame timestamps across cameras are comparable — needed to correlate, e.g., heart rate against tail-driven swim bouts.

**Basler**: already supported (`pypylon`, official PyPI package — no changes needed beyond dependency bump).
**IDS**: new backend needed. Recommend `ids_peak` (IDS's current official Python API) as primary, since IDS is moving away from the legacy `pyueye`; `pyueye` as a fallback if you already have that SDK installed. Both are vendor-distributed, not on PyPI — same caveat as above.

## 3. New tracking pipelines: heart rate & pectoral fin

Both plug into the existing `Pipeline`/`PipelineNode` DAG framework (`stytra/tracking/pipelines.py`) rather than replacing it — same pattern as tail/eye tracking.

- **Heart rate**: ROI → per-frame scalar signal (mean intensity, or frame-to-frame phase correlation within the ROI) → rolling-window bandpass filter + peak detection → BPM. Numba-jitted like the existing tail-angle code, so it stays cheap enough to run at full frame rate per camera.
- **Pectoral fin**: ROI → per-frame fin-blade estimate. Two candidate approaches: (a) optical flow (Lucas-Kanade) on tracked fin-tip keypoints, or (b) threshold + PCA on the ROI mask each frame to get a fin-angle time series. Recommend starting with (b) since it mirrors the existing tail centerline approach and is cheaper; can add optical flow later if angular resolution isn't enough.

ROI drawing for both reuses the existing draggable-ROI GUI infrastructure, just with new `HeartROISelection` / `FinROISelection` widget subclasses.

## 4. Projector / stimulus display

Current setup already composites onto a `QOpenGLWidget` surface (so display is already GPU-composited), but each stimulus is still software-rasterized per frame via `QPainter` calls — this is the actual CPU bottleneck for complex/high-framerate stimuli, not the output path. Recommend: keep the existing `QPainter` path as the default (simplest, works for most stimuli), and add an **opt-in** true-shader rendering path (e.g. via `moderngl` bound into the same `QOpenGLWidget` context) for specific stimuli that need it. This avoids rewriting every existing stimulus class.

## 5. Zarr for image data

New `ZarrVideoWriter` alongside the existing `H5VideoWriter`/`StreamingVideoWriter`, selectable per experiment:
- Chunked, blosc-compressed, frame-by-frame append (no more buffering the whole video in RAM like `H5VideoWriter` does today).
- One Zarr store per experiment, one array per camera (e.g. `tail_cam`, `heart_cam` groups) so multi-camera recordings land in a single coherent store.
- Per-frame timestamps and acquisition metadata as Zarr attrs.
- Config/metadata (small, not perf-critical) stays on `flammkuchen`/HDF5 unless you'd rather unify everything under Zarr — your call, listed as an open question below.

## 6. Performance / IPC

Replace `arrayqueues` with an in-house ring buffer on stdlib `multiprocessing.shared_memory` — pre-allocated, fixed-size frame slots (sized from camera resolution/dtype at experiment start), true zero-copy across processes. Also replaces the current crude backpressure (`qsize() < n_consumers + 2`, drop-and-log) with adaptive skipping keyed off actual consumer lag rather than a fixed threshold. This is the single highest-leverage change for both "fix known crashes" and "make it fast."

## 7. Phased delivery plan

1. **Python 3.12 port**: dependency swap (`arrayqueues` → in-house shared-memory queue, `pyFirmata` → `pyfirmata2`), `pyproject.toml`, CI matrix update, tests green on 3.12.
2. **Camera manager**: multi-vendor `list_devices()`, unified detection, new IDS backend, live-preview "Camera Setup" screen.
3. **Multi-camera acquisition**: N cameras / N tracking processes running concurrently, shared clock reference.
4. **New tracking pipelines**: heart-rate + pectoral-fin, ROI selection GUI extension.
5. **Zarr video writer**, wired into the experiment save flow, selectable alongside existing writers.
6. **Stimulus/perf polish**: optional shader stimulus path, GUI tiling for multi-camera live view, styling pass.

Each phase is independently shippable and testable before moving to the next.

## 8. Decisions (resolved 2026-07-14)

1. **IDS SDK**: `ids_peak` — already installed, use it as primary/only backend for now.
2. **Minimum Python version**: floor is **3.10**, primary target/CI is **3.12**.
3. **Heart-rate algorithm**: designed from scratch, starting from ROI intensity changes driven by blood flow (as proposed in §3) — open to iterating on the method once we have real data.
4. **Zarr scope**: image/video data only. **Not** migrating `flammkuchen`/HDF5 config+metadata — see rationale below.
5. **Vendor SDK access**: no AVT/Ximea/FLIR/Mikrotron wheels on hand. Those backends are **deferred** — code stays in place behind the existing lazy-import guards, but isn't part of the active Python 3.12 test/support matrix until wheels are available. Active camera backends for this pass: OpenCV (generic UVC), Basler (`pypylon`), IDS (`ids_peak`).

**Rationale for #4**: Zarr's chunked-array model is a good fit for video frames (that's where the RAM-buffering bug and the perf win actually are). Your experiment config/metadata is small, deeply-nested parameter dicts, not large arrays — `flammkuchen`/HDF5 already handles that fine and isn't a bottleneck. Migrating it would touch every experiment's save/load path for no performance or capability gain, purely for the sake of using one format everywhere. Recommend leaving it on `flammkuchen`, and revisiting only if a concrete need shows up later (e.g. wanting a single self-contained store per experiment).

## 9. `flammkuchen` and `lightparam` — Python 3.12 compatibility check

Both are local sibling checkouts (`/Users/nikolai/Documents/GitHub/flammkuchen`, `/Users/nikolai/Documents/GitHub/lightparam`), so we can patch them directly rather than treating them as black-box PyPI installs.

- **flammkuchen**: pure Python + `numpy`/`scipy`/`tables` (PyTables). No deprecated-API usage found (no `np.float`/`np.int` aliases, no `distutils`, no `collections.Mapping`). PyTables ≥3.9 supports Python 3.12. Classifiers still claim 3.6–3.9 only. Action: bump classifiers/`python_requires`, bump the `tables` pin, test under 3.12 — expect this to be low-effort.
- **lightparam**: pure Python + PyQt5. Same clean scan, no deprecated APIs found. Classifiers claim 3.5–3.7 (stale). PyQt5 ≥5.15.9 supports 3.12, so no Qt-binding migration forced. Action: same as above — bump classifiers/pins, test under 3.12.

Neither package looks like it needs substantive rewriting for 3.12; this is mostly a metadata/pin bump + verification pass. Will fix anything that surfaces once tests actually run under 3.12.
