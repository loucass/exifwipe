"""exifwipe.py - thin public face of the split exifwipe modules.

Everything lives in a flat family of `_*.py` modules next to this file.
This facade re-exports the whole public + internal API so `import exifwipe`
(and the tests) keep working unchanged.
"""

from __future__ import annotations

import _color as _color
import _config as _config
import _inspect as _inspect
import _verify as _verify
import _tiff as _tiff
import _pixels as _pixels
import _jpeg as _jpeg
import _gif as _gif
import _png as _png
import _webp as _webp
import _heif as _heif
import _raf as _raf
import _pdf as _pdf
import _report as _report
import _driver as _driver
import _menu as _menu
import _cli as _cli

from _color import _can_color, _COLOR, set_color, _c, c_ok, c_err, c_warn, c_info, c_head, c_dim, c_mag, c_blue
from _config import IMAGE_EXTS, DOC_EXTS, R_OK, R_ERR, R_SKIP, RASTER_FORMATS, IMAGE_FORMATS, RAW_FORMATS, RAW_EXTENSIONS, SUPPORTED_FORMATS, DEFAULT_MAX_PIXELS, _SYSTEM_DIRS, _RAF_MAGIC, _MAKERNOTE_VENDORS, _PNG_SIG, _HEIF_META_TYPES, _MENU_ART
from _inspect import inspect_image, exiftool_hint
from _verify import _STRUCTURAL_KEYS, _STRUCTURAL_GROUPS, _parse_exiftool_json, _verify_with_exiftool, _verify_bytes, verify_clean, print_formats_matrix
from _tiff import _TIFF_IDENTIFYING, _TIFF_BLANK, _tiff_layout, _TYPE_SIZE, _tiff_parse_header, _iter_tiff_entries, _tiff_value_bytes, _value_is_blank, _tiff_find_identifying, _tiff_inventory, _tiff_protected_regions, _overlaps_protected, _tiff_structure_ok, _tiff_has_tag, _tiff_vendor_from_makernote, _is_tiff_family, _tiff_strip_lossless
from _pixels import _apply_orientation, _perturb_seed, _perturb_image, _rebuild_frame, _strip_multiframe
from _jpeg import _jpeg_orientation_from_bytes, _jpeg_sof_size, _orientation_is_neutral, _entropy_marker_index, _split_jpeg_frames, _jpeg_metadata_segments, _jpeg_final_check, _rebuild_jpeg_from_img, _strip_mpo_rotated_first, _strip_jpeg_lossless
from _gif import _strip_gif_lossless, _skip_gif_subblocks, _copy_gif_subblocks
from _png import _png_is_animated, _strip_png_lossless
from _webp import _webp_is_lossless
from _heif import _heif_box_children, _heif_iloc_items, _heif_item_types, _heif_infe_item_id, _heif_exif_payload_present, _heif_metadata_extents, _strip_heif_lossless
from _raf import _strip_raf_lossless
from _pdf import strip_pdf_bytes
from _report import _inventory_metadata, _print_report
from _driver import strip_image_bytes, handle_one, iter_inputs
from _sniff import _sniff_bytes, _sniff_format
from _write import _atomic_write_bytes, write_output, _refuse_system_target
from _menu import print_top_banner, prompt_input, _clear_screen, _pause_if_tty, _run_menu_action, _state, menu_choose, run_interactive_menu
from _cli import build_parser, main
from _config import __version__, __author__, __github__, __license__
from _driver import pillow_heif
from _cli import piexif


if __name__ == "__main__":
    raise SystemExit(main())
