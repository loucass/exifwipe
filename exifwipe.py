"""exifwipe - thin public face of the exifwipe modules.

The real code lives in `lib/` (one module per format/concern). This
facade re-exports the whole public + internal API so `import exifwipe`
(and the tests) keep working unchanged.
"""

from __future__ import annotations

import lib._color as _color
import lib._config as _config
import lib._inspect as _inspect
import lib._verify as _verify
import lib._tiff as _tiff
import lib._pixels as _pixels
import lib._jpeg as _jpeg
import lib._gif as _gif
import lib._png as _png
import lib._webp as _webp
import lib._heif as _heif
import lib._raf as _raf
import lib._pdf as _pdf
import lib._report as _report
import lib._sniff as _sniff
import lib._write as _write
import lib._driver as _driver
import lib._menu as _menu
import lib._cli as _cli

from lib._color import _c, _can_color, c_blue, c_danger, c_dim, c_err, c_head, c_info, c_mag, c_ok, c_warn, set_color
from lib._config import DEFAULT_MAX_PIXELS, DOC_EXTS, IMAGE_EXTS, IMAGE_FORMATS, RASTER_FORMATS, RAW_EXTENSIONS, RAW_FORMATS, R_ERR, R_OK, R_SKIP, SUPPORTED_FORMATS
from lib._inspect import _Pager, _anomalies, _decode_ascii, _format_value, _img_info_value, _inspect_gif, _inspect_heif, _inspect_jpeg, _inspect_pdf, _inspect_png, _inspect_raf, _inspect_webp, _size_str, _tag_name, _walk_tiff, exiftool_hint, inspect_image
from lib._verify import _parse_exiftool_json, _verify_bytes, _verify_with_exiftool, print_formats_matrix, verify_clean
from lib._tiff import _is_tiff_family, _iter_tiff_entries, _overlaps_protected, _tiff_find_identifying, _tiff_has_tag, _tiff_inventory, _tiff_layout, _tiff_parse_header, _tiff_protected_regions, _tiff_strip_lossless, _tiff_structure_ok, _tiff_value_bytes, _tiff_vendor_from_makernote, _value_is_blank
from lib._pixels import _apply_orientation, _perturb_image, _perturb_seed, _rebuild_frame, _strip_multiframe
from lib._jpeg import _entropy_marker_index, _jpeg_final_check, _jpeg_metadata_segments, _jpeg_orientation_from_bytes, _jpeg_sof_size, _orientation_is_neutral, _rebuild_jpeg_from_img, _split_jpeg_frames, _strip_jpeg_lossless, _strip_mpo_rotated_first
from lib._gif import _copy_gif_subblocks, _skip_gif_subblocks, _strip_gif_lossless
from lib._png import _png_is_animated, _strip_png_lossless
from lib._webp import _webp_is_lossless
from lib._heif import _heif_box_children, _heif_exif_payload_present, _heif_iloc_items, _heif_infe_item_id, _heif_item_types, _heif_metadata_extents, _strip_heif_lossless
from lib._raf import _strip_raf_lossless
from lib._pdf import strip_pdf_bytes
from lib._report import _inventory_metadata, _print_report
from lib._sniff import _sniff_bytes, _sniff_format
from lib._write import _atomic_write_bytes, _refuse_system_target, write_output
from lib._driver import handle_one, iter_inputs, strip_image_bytes
from lib._menu import _clear_screen, _pause_if_tty, _run_menu_action, _state, menu_choose, print_top_banner, prompt_input, run_interactive_menu
from lib._cli import build_parser, main
from lib._config import __version__, __author__, __github__, __license__
from lib._driver import pillow_heif
from lib._cli import piexif


if __name__ == "__main__":
    raise SystemExit(main())
