"""Copy the bundled blueprints and Assist sentences into the user's config.

Home Assistant only reads blueprints from ``<config>/blueprints`` and custom
sentences from ``<config>/custom_sentences``, and the Marketplace/HACS installs
nothing but this integration's own folder. So the integration places its
ready-made files there when it starts.

A file is only created or refreshed when it is absent or is one of ours (it
carries our marker). A file the user copied and edited under the same name is
never overwritten.
"""

import logging
import shutil
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
BLUEPRINT_SOURCE = PACKAGE_DIR / "blueprints" / "automation" / "vigobus"
SENTENCES_SOURCE = PACKAGE_DIR / "custom_sentences"

BLUEPRINT_MARKER = "github.com/MUbeira0/vigobus-integration"
SENTENCES_MARKER = "Managed by VigoBus Pro"


def _is_ours(path, marker):
    try:
        return marker in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _copy_if_ours(source, destination, marker):
    """Copy ``source`` to ``destination``; True when the file was written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not _is_ours(destination, marker):
            _LOGGER.debug("VigoBus: leaving the customised file %s untouched", destination)
            return False
        if destination.read_bytes() == source.read_bytes():
            return False
    shutil.copyfile(source, destination)
    return True


def install_assets(config_dir):
    """Blocking: install blueprints and sentences. Returns what changed.

    ``config_dir`` is Home Assistant's configuration folder. The result is
    ``{"blueprints": [names], "sentences": [languages]}`` listing only the
    files that were created or updated.
    """
    config = Path(config_dir)
    changed = {"blueprints": [], "sentences": []}

    if BLUEPRINT_SOURCE.is_dir():
        target_dir = config / "blueprints" / "automation" / "vigobus"
        for source in sorted(BLUEPRINT_SOURCE.glob("*.yaml")):
            if _copy_if_ours(source, target_dir / source.name, BLUEPRINT_MARKER):
                changed["blueprints"].append(source.name)

    if SENTENCES_SOURCE.is_dir():
        for language_dir in sorted(p for p in SENTENCES_SOURCE.iterdir() if p.is_dir()):
            source = language_dir / "vigobus.yaml"
            if not source.is_file():
                continue
            destination = config / "custom_sentences" / language_dir.name / "vigobus.yaml"
            if _copy_if_ours(source, destination, SENTENCES_MARKER):
                changed["sentences"].append(language_dir.name)

    return changed


async def async_install_assets(hass):
    """Install the assets without blocking the event loop; never raises."""
    try:
        changed = await hass.async_add_executor_job(install_assets, hass.config.config_dir)
    except Exception:
        _LOGGER.warning("VigoBus: unable to install the bundled blueprints and sentences", exc_info=True)
        return {"blueprints": [], "sentences": []}

    if changed["sentences"] and hass.services.has_service("conversation", "reload"):
        # Make Assist pick up new or updated sentences without a restart.
        try:
            await hass.services.async_call("conversation", "reload", {}, blocking=False)
        except Exception:
            _LOGGER.debug("VigoBus: unable to reload the conversation sentences", exc_info=True)

    if changed["blueprints"] or changed["sentences"]:
        _LOGGER.info(
            "VigoBus: installed blueprints %s and sentences %s",
            changed["blueprints"],
            changed["sentences"],
        )
    return changed
