#!/usr/bin/env python3
import os
import sys
import re
import shutil
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Tuple
from PIL import Image


@dataclass
class DateResult:
    date: datetime
    source: str
    subsecond: Optional[str] = None


class PhotoOrganizer:
    DATETIME_EXIF_TAG = 36867
    SUBSEC_TIME_ORIGINAL_TAG = 37521

    EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif',
                  'nef', 'dng', 'cr2', 'arw', 'orf', 'rw2',
                  'mov', 'mp4', 'avi', 'mkv', '3gp']

    EXIFTOOL_EXTENSIONS = ['mov', 'mp4', 'avi', 'mkv', '3gp',
                           'nef', 'dng', 'cr2', 'arw', 'orf', 'rw2',
                           'heic', 'heif']

    DATE_FOLDER_PATTERN = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')

    FILENAME_PATTERNS = [
        (re.compile(r'IMG_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'android_camera'),
        (re.compile(r'VID_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'android_video'),
        (re.compile(r'PXL_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'pixel'),
        (re.compile(r'MVIMG_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'motion_photo'),
        (re.compile(r'P_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'huawei_photo'),
        (re.compile(r'V_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'huawei_video'),
        (re.compile(r'Screenshot_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})'), 'screenshot'),
        (re.compile(r'Screenshot_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})'), 'screenshot_alt'),
        (re.compile(r'IMG-(\d{4})(\d{2})(\d{2})-WA\d+'), 'whatsapp'),
        (re.compile(r'VID-(\d{4})(\d{2})(\d{2})-WA\d+'), 'whatsapp_video'),
        (re.compile(r'photo_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})'), 'telegram'),
        (re.compile(r'video_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})'), 'telegram_video'),
        (re.compile(r'DCIM_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'), 'dcim'),
        (re.compile(r'DSC_?(\d{4})(\d{2})(\d{2})_?(\d{2})(\d{2})(\d{2})'), 'dsc'),
        (re.compile(r'^(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})\.(\d{2})'), 'datetime_dots'),
    ]

    def __init__(self, inbox: Optional[Path], archive: Path, unsorted: Path,
                 dry_run: bool = False, reprocess: bool = False):
        self.inbox = inbox
        self.archive = archive
        self.unsorted = unsorted
        self.dry_run = dry_run
        self.reprocess = reprocess
        self.logger = logging.getLogger(__name__)

    def has_valid_extension(self, filename: str) -> bool:
        return any(filename.lower().endswith('.' + ext.lower())
                   for ext in self.EXTENSIONS)

    def uses_exiftool(self, filename: str) -> bool:
        return any(filename.lower().endswith('.' + ext.lower())
                   for ext in self.EXIFTOOL_EXTENSIONS)

    def extract_date_from_folder(self, folder_name: str) -> Optional[datetime]:
        match = self.DATE_FOLDER_PATTERN.match(folder_name)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
        return None

    def extract_exif_date(self, filepath: Path) -> Optional[DateResult]:
        if self.uses_exiftool(filepath.name):
            return self._extract_exif_via_exiftool(filepath)
        return self._extract_exif_via_pil(filepath)

    def _extract_exif_via_exiftool(self, filepath: Path) -> Optional[DateResult]:
        date_tags = ["Date/Time Original", "Create Date", "Media Create Date"]
        subsec_tags = ["Sub Sec Time Original", "Sub-Sec Time Original"]

        try:
            cmd = ["exiftool", str(filepath)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return None

            lines = result.stdout.split("\n")
            date_value = None
            subsecond = None

            for line in lines:
                if " : " not in line:
                    continue
                tag, value = line.split(" : ", 1)
                tag = tag.strip()
                value = value.strip()

                if date_value is None:
                    for date_tag in date_tags:
                        if date_tag in tag:
                            date_value = value
                            break

                if subsecond is None:
                    for subsec_tag in subsec_tags:
                        if subsec_tag in tag:
                            subsecond = value.strip()[:3]
                            break

            if date_value:
                date_str = date_value.split('.')[0].split('+')[0].split('-')[0]
                date = datetime.strptime(date_str.strip(), "%Y:%m:%d %H:%M:%S")
                return DateResult(date=date, source="exif", subsecond=subsecond)

        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            self.logger.warning(f"exiftool failed for {filepath}: {e}")
        except ValueError as e:
            self.logger.warning(f"Date parsing failed for {filepath}: {e}")

        return None

    def _extract_exif_via_pil(self, filepath: Path) -> Optional[DateResult]:
        try:
            with Image.open(filepath) as img:
                if not hasattr(img, '_getexif'):
                    return None
                exif = img._getexif()
                if not exif:
                    return None

                date_str = exif.get(self.DATETIME_EXIF_TAG)
                if not date_str:
                    return None

                subsecond = exif.get(self.SUBSEC_TIME_ORIGINAL_TAG)
                if subsecond:
                    subsecond = str(subsecond).strip()[:3]

                date = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                return DateResult(date=date, source="exif", subsecond=subsecond)

        except (OSError, ValueError) as e:
            self.logger.warning(f"PIL EXIF extraction failed for {filepath}: {e}")

        return None

    def extract_date_from_filename(self, filename: str) -> Optional[DateResult]:
        for pattern, source in self.FILENAME_PATTERNS:
            match = pattern.search(filename)
            if match:
                groups = match.groups()
                try:
                    if len(groups) >= 6:
                        date = datetime(
                            int(groups[0]), int(groups[1]), int(groups[2]),
                            int(groups[3]), int(groups[4]), int(groups[5])
                        )
                    elif len(groups) == 3:
                        date = datetime(int(groups[0]), int(groups[1]), int(groups[2]))
                    else:
                        continue
                    return DateResult(date=date, source=f"filename:{source}")
                except ValueError:
                    continue
        return None

    def get_date(self, filepath: Path) -> DateResult:
        result = self.extract_exif_date(filepath)
        if result:
            return result

        result = self.extract_date_from_filename(filepath.name)
        if result:
            return result

        # Fallback to mtime as per Aves sync issue recommendation
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        return DateResult(date=mtime, source="mtime")

    def write_exif_date(self, filepath: Path, date: datetime) -> bool:
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would write EXIF date {date} to {filepath}")
            return True

        date_str = date.strftime("%Y:%m:%d %H:%M:%S")
        # -AllDates sets DateTimeOriginal, CreateDate, and ModifyDate
        tags = ["-AllDates=" + date_str]

        try:
            # -overwrite_original prevents creating ._original files
            cmd = ["exiftool", "-overwrite_original"] + tags + [str(filepath)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Failed to write EXIF to {filepath}: {e}")
            return False

    def get_target_folder(self, date: datetime) -> Path:
        year = date.strftime('%Y')
        date_folder = date.strftime('%Y-%m-%d')
        return self.archive / year / date_folder

    def get_unsorted_folder(self) -> Path:
        return self.unsorted / "1970" / "1970-01-01"

    def resolve_collision(self, target_path: Path) -> Path:
        if not target_path.exists():
            return target_path

        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent

        counter = 1
        while True:
            new_name = f"{stem}_{counter:03d}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return new_path
            counter += 1
            if counter > 999:
                raise RuntimeError(f"Too many collisions for {target_path}")

    def is_in_correct_folder(self, filepath: Path, date: datetime) -> bool:
        expected_year = date.strftime('%Y')
        expected_date_prefix = date.strftime('%Y-%m-%d')

        parts = filepath.parts
        if len(parts) < 2:
            return False

        folder_name = parts[-2]
        folder_year = parts[-3] if len(parts) >= 3 else None

        return folder_name.startswith(expected_date_prefix) and folder_year == expected_year

    def process_file(self, filepath: Path) -> bool:
        if not self.has_valid_extension(filepath.name):
            return False

        self.logger.info(f"Processing: {filepath}")

        date_result = self.get_date(filepath)

        if date_result.source == "mtime":
            if self.reprocess:
                folder_name = filepath.parent.name
                folder_date = self.extract_date_from_folder(folder_name)
                if folder_date:
                    self.logger.debug(f"No EXIF but in valid date folder, skipping: {filepath}")
                    return True
            self.logger.warning(f"No date found in metadata/filename, moving to unsorted: {filepath}")
            target_folder = self.get_unsorted_folder()
        else:
            if self.is_in_correct_folder(filepath, date_result.date):
                self.logger.debug(f"File already in correct folder: {filepath}")
                # We still might want to write EXIF if it's missing (e.g. filename source)
                # but we'll skip that for already sorted files unless explicitly requested
                return True
            target_folder = self.get_target_folder(date_result.date)

        target_path = target_folder / filepath.name
        target_path = self.resolve_collision(target_path)

        self._move_file(filepath, target_path)

        # Write EXIF if source is filename or mtime to prevent sync date issues
        if date_result.source != "exif":
            self.logger.info(f"Baking date ({date_result.date}) into EXIF for {target_path}")
            self.write_exif_date(target_path, date_result.date)

        self.logger.info(f"Organized: {filepath.name} -> {target_path} ({date_result.source})")
        return True

    def _move_file(self, source: Path, target: Path) -> None:
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would move: {source} -> {target}")
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

    def collect_files_inbox(self) -> list[Path]:
        if not self.inbox or not self.inbox.exists():
            return []

        files = []
        for item in self.inbox.iterdir():
            if item.is_file() and self.has_valid_extension(item.name):
                files.append(item)
        return sorted(files)

    def collect_files_reprocess(self) -> list[Path]:
        if not self.archive.exists():
            return []

        files = []
        for root, _, filenames in os.walk(self.archive):
            for filename in filenames:
                filepath = Path(root) / filename
                if self.has_valid_extension(filename):
                    files.append(filepath)
        return sorted(files)

    def organize(self) -> Tuple[int, int, int]:
        if self.reprocess:
            files = self.collect_files_reprocess()
            self.logger.info(f"Reprocessing {len(files)} files from archive")
        else:
            files = self.collect_files_inbox()
            self.logger.info(f"Processing {len(files)} files from inbox")

        success = 0
        failed = 0
        skipped = 0

        for filepath in files:
            try:
                if self.process_file(filepath):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                self.logger.error(f"Error processing {filepath}: {e}")
                self._handle_error_file(filepath, str(e))
                failed += 1

        return success, failed, skipped

    def _handle_error_file(self, filepath: Path, error_msg: str) -> None:
        error_folder = self.unsorted / "errors"
        target_path = error_folder / filepath.name
        target_path = self.resolve_collision(target_path)

        if not self.dry_run:
            try:
                self._move_file(filepath, target_path)
                self.logger.info(f"Moved errored file to: {target_path}")
            except Exception as e:
                self.logger.error(f"Failed to move errored file {filepath}: {e}")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Organize photos into YYYY/YYYY-MM-DD folder structure by EXIF date',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  Process inbox:
    %(prog)s --inbox ~/Photos/inbox --archive ~/Photos/archive

  Reprocess existing archive:
    %(prog)s --reprocess ~/Photos/archive

  Dry run (no changes):
    %(prog)s --inbox ~/Photos/inbox --archive ~/Photos/archive --dry-run
'''
    )

    parser.add_argument('--inbox', type=Path,
                        help='Input directory with unorganized files')
    parser.add_argument('--archive', type=Path, required=True,
                        help='Output directory for organized files (YYYY/YYYY-MM-DD structure)')
    parser.add_argument('--unsorted', type=Path,
                        help='Directory for files without extractable dates (default: archive/../unsorted)')
    parser.add_argument('--reprocess', action='store_true',
                        help='Recursively reprocess existing archive')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-d', '--directory', type=Path,
                        help='Legacy: same as --inbox')

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    inbox = args.inbox or args.directory
    if args.reprocess:
        if inbox:
            logger.warning("--inbox ignored when using --reprocess")
        inbox = None
    elif not inbox:
        parser.error("Either --inbox or --reprocess is required")

    unsorted = args.unsorted
    if not unsorted:
        unsorted = args.archive.parent / "unsorted"

    if args.dry_run:
        logger.info("DRY-RUN MODE: No files will be modified")

    organizer = PhotoOrganizer(
        inbox=inbox,
        archive=args.archive,
        unsorted=unsorted,
        dry_run=args.dry_run,
        reprocess=args.reprocess
    )

    success, failed, skipped = organizer.organize()

    logger.info(f"Complete: {success} organized, {failed} failed/unsorted, {skipped} skipped")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
