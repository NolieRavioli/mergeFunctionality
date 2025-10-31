# fetchers/public/static_data.py

import os
import requests
import zipfile
import shutil
import yaml
import logging
import time

from util.sde import refresh_all_caches, build_universe_table

logger = logging.getLogger(__name__)

# ──────── Constants ─────────────────────────────────────────────────────────────

SDE_URL = "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"
SDE_PATH = os.getenv("SDE_PATH", "_sde/")
SDE_ZIP_PATH = "_sde_tmp.zip"

FIELDS_TO_CLEAN = [
    "name", "description", "shortDescription",
    "descriptionID", "nameID", "displayNameID", "tooltipDescriptionID",
    "leaderTypeNameID", "serviceNameID", "operationNameID"
]
SUPPORTED_LANGUAGES = os.getenv("SUPPORTED_LANGUAGES", "en").split(",")
SUPPORTED_LANGUAGES = [lang.strip() for lang in SUPPORTED_LANGUAGES if lang.strip()]

# ──────── Core Functions ─────────────────────────────────────────────────────────

def download_sde(url=SDE_URL, dest=SDE_ZIP_PATH, retries=3):
    backoff = 2
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Downloading SDE (attempt {attempt})...")
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("SDE download complete.")
            return
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(backoff)
                backoff *= 2
            else:
                raise RuntimeError("Failed to download SDE after multiple attempts.")

def unzip_sde(zip_path=SDE_ZIP_PATH, extract_to=SDE_PATH):
    if os.path.exists(extract_to):
        logger.info(f"Cleaning up existing {extract_to} folder.")
        shutil.rmtree(extract_to)
    os.makedirs(extract_to, exist_ok=True)

    logger.info(f"Extracting {zip_path} to {extract_to}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    logger.info("Extraction complete.")

def cleanup(zip_path=SDE_ZIP_PATH):
    if os.path.exists(zip_path):
        os.remove(zip_path)
        logger.info("Cleaned up temporary SDE zip.")

def clean_multilang_fields(data):
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if key in FIELDS_TO_CLEAN and isinstance(value, dict):
                cleaned[key] = {lang: value[lang] for lang in SUPPORTED_LANGUAGES if lang in value}
            else:
                cleaned[key] = clean_multilang_fields(value)
        return cleaned
    elif isinstance(data, list):
        return [clean_multilang_fields(item) for item in data]
    else:
        return data

def migrate_sde_inplace(fsd_dir=None):
    if fsd_dir is None:
        fsd_dir = os.path.join(SDE_PATH, "fsd")

    if not os.path.exists(fsd_dir):
        logger.warning(f"No fsd folder found at {fsd_dir}, skipping migration.")
        return

    logger.info("Migrating SDE FSD YAMLs to supported languages only...")
    for root, dirs, files in os.walk(fsd_dir):
        for file in files:
            if file.endswith(".yaml"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.load(f, Loader=yaml.CLoader)
                    cleaned = clean_multilang_fields(data)
                    with open(path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(cleaned, f, allow_unicode=True)
                except Exception as e:
                    logger.error(f"Error processing {path}: {e}")
    logger.info("SDE migration complete.")

def update_sde():
    """Main entrypoint to update SDE."""
    download_sde()
    unzip_sde()
    migrate_sde_inplace()
    cleanup()
    refresh_all_caches()
    build_universe_table()
    logger.info("SDE helpers refreshed after update.")

# ──────── Run Script ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    update_sde()
