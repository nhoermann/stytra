======
Stytra
======

A modular package to control stimulation and track behavior in zebrafish experiments.
---------------

.. image:: https://cdn.rawgit.com/portugueslab/stytra/644a23d5/stytra/icons/stytra_logo.svg
    :scale: 50%
    :alt: Logo

.. image:: https://zenodo.org/badge/DOI/10.5281/zenodo.3238310.svg
   :target: https://doi.org/10.5281/zenodo.3238310


If you are using Stytra for your own research, please `cite the original authors <https://doi.org/10.1371/journal.pcbi.1006699>`_!

This is a fork of `portugueslab/stytra <https://github.com/portugueslab/stytra>`_, modernized for Python 3.10-3.12 and
extended with multi-camera acquisition, heart-rate/pectoral-fin tracking, and several other changes described below.
The original project's `documentation <http://www.portugueslab.com/stytra>`_ and
`example gallery <http://www.portugueslab.com/stytra/userguide/1_examples_gallery.html>`_ still describe the core
concepts (Protocols, Stimuli, tracking Pipelines) accurately, since this fork builds on top of that architecture
rather than replacing it - just note that some install instructions and API details there predate the changes in
this fork.

Stytra is divided into independent modules which can be assembled depending on the experimental requirements:
stimulus display and control, camera acquisition and closed-loop tracking, and data logging.

Disclaimer
----------

This fork comes with **no guarantees that it will work**. Large parts of it (the new tracking pipelines, the
multi-camera architecture, Zarr storage, ScanImage triggering) have only been validated with synthetic data,
recorded video, or automated tests - not against real cameras, real embedded-fish footage, or a real projector/
rig. Some known issues are tracked but not yet fixed (see `docs/MODERNIZATION_PROPOSAL.md <docs/MODERNIZATION_PROPOSAL.md>`_).
Use at your own risk, verify carefully against your own hardware and data before relying on it for real
experiments, and expect to find and fix things.

Capabilities
------------

Beyond the original project, this fork adds:

- **Python 3.10-3.12 support.** Dependencies that were unmaintained or broken on modern Python
  (``arrayqueues``, ``flammkuchen``, ``pyFirmata``) have been replaced with a custom zero-copy shared-memory
  queue, thin `PyTables <https://www.pytables.org/>`_ helpers, and ``pyfirmata2`` respectively.
- **Multi-camera acquisition and tracking.** Any number of cameras can run concurrently, each with its own
  independent tracking pipeline and recording settings, via a ``cameras=[...]`` config list (the legacy
  single-camera ``camera=``/``tracking=``/``recording=`` config keeps working unchanged).
- **Heart-rate and pectoral-fin tracking**, alongside the existing tail/eye/multi-fish tracking pipelines -
  ROI-based, running at full frame rate per camera.
- **Camera auto-detection and an interactive Camera Setup dialog** to pick which detected cameras to use and
  assign each a role and tracking method, with save/load of named setups. Includes support for adding a
  video/HDF5 file as a "simulated camera", so a full multi-camera experiment can be built and tested with no
  hardware attached at all.
- **A tiled multi-camera GUI**: one live preview dock per camera, each with its own ROI overlay and
  tracking-parameter controls.
- **Zarr-based video storage** as a streaming, chunked, compressed alternative to the existing HDF5/mp4 writers,
  selectable per camera.
- **ScanImage acquisition triggering** via the MATLAB Engine API.
- Assorted GUI safety/usability improvements: a confirmation prompt before closing a window mid-protocol,
  warnings/errors surfaced in the persistent log (not just a fading status bar), and a couple of real bug fixes
  (a canceled save-folder dialog silently blanking the save path; a PyQt5 float/int crash in the calibration
  overlay).

See `docs/MODERNIZATION_PROPOSAL.md <docs/MODERNIZATION_PROPOSAL.md>`_ for the full history of these changes,
including what's been verified against real hardware and what still needs it.
