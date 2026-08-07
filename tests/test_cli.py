"""CLI end-to-end: exit-code contract, dry-run, -o semantics, guards."""

import io

import pytest
from PIL import Image

import exifwipe
from helpers import (assert_jpeg_clean, assert_png_clean, jpeg_with_exif,
                     png_with_metadata)


def test_version_flag():
    with pytest.raises(SystemExit) as e:
        exifwipe.main(["--version"])
    assert e.value.code == 0


def test_formats_flag(capsys):
    assert exifwipe.main(["--formats"]) == 0
    out = capsys.readouterr().out
    assert "jpeg" in out and "pdf" in out


def test_missing_input_exit_2():
    assert exifwipe.main(["/nonexistent/path/xyz.jpg"]) == 2


def test_strip_in_place_exit_0(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "in.jpg")
    assert exifwipe.main([str(src)]) == 0
    assert_jpeg_clean(src.read_bytes())


def test_dry_run_writes_nothing(tmp_path):
    src = jpeg_with_exif(tmp_path / "dry.jpg")
    before = src.read_bytes()
    assert exifwipe.main([str(src), "--dry-run"]) == 0
    assert src.read_bytes() == before


def test_inspect_writes_nothing(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "insp.jpg")
    before = src.read_bytes()
    assert exifwipe.main([str(src), "--inspect"]) == 0
    assert src.read_bytes() == before
    assert "AttackerCam" in capsys.readouterr().out


def test_unrecognized_input_skipped_exit_0(tmp_path, capsys):
    p = tmp_path / "readme.txt"
    p.write_text("hello")
    assert exifwipe.main([str(p)]) == 0
    assert "1 skipped" in capsys.readouterr().out


def test_output_file_single_input(tmp_path):
    src = jpeg_with_exif(tmp_path / "src.jpg")
    out = tmp_path / "out.jpg"
    assert exifwipe.main([str(src), "-o", str(out)]) == 0
    assert_jpeg_clean(out.read_bytes())


def test_output_file_with_multiple_inputs_refused(tmp_path):
    a = jpeg_with_exif(tmp_path / "a.jpg")
    b = jpeg_with_exif(tmp_path / "b.jpg")
    assert exifwipe.main([str(tmp_path), "-o", str(tmp_path / "single.jpg")]) == 2


def test_output_dir_duplicate_basenames_disambiguated(tmp_path):
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    a = jpeg_with_exif(tmp_path / "sub1" / "a.jpg")
    b = jpeg_with_exif(tmp_path / "sub2" / "a.jpg")
    outdir = tmp_path / "clean"
    assert exifwipe.main([str(tmp_path), "-o", str(outdir)]) == 0
    names = sorted(p.name for p in outdir.iterdir())
    assert "a.jpg" in names and "a (2).jpg" in names, f"got {names}"
    assert_jpeg_clean((outdir / "a.jpg").read_bytes())
    assert_jpeg_clean((outdir / "a (2).jpg").read_bytes())


def test_output_dir_created(tmp_path):
    src = jpeg_with_exif(tmp_path / "x.jpg")
    outdir = tmp_path / "made" / "clean"
    assert exifwipe.main([str(src), "-o", str(outdir)]) == 0
    assert (outdir / "x.jpg").is_file()


def test_system_dir_output_refused(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "x.jpg")
    rc = exifwipe.main([str(src), "-o", "/etc/exifwipe_test_out"])
    assert rc == 3
    assert "refusing" in capsys.readouterr().err


def test_verify_passes_clean_exit_0(tmp_path):
    src = jpeg_with_exif(tmp_path / "v.jpg")
    assert exifwipe.main([str(src), "--verify"]) == 0


def test_keep_icc_via_cli(tmp_path):
    src = jpeg_with_exif(tmp_path / "icc.jpg", icc=True)
    out = tmp_path / "kept.jpg"
    assert exifwipe.main([str(src), "--keep-icc", "-o", str(out)]) == 0
    assert b"ICC_PROFILE\x00" in out.read_bytes()


def test_folder_batch_mixed_content(tmp_path, capsys):
    jpeg_with_exif(tmp_path / "photo.jpg")
    (tmp_path / "notes.txt").write_text("hello")
    png_with_metadata(tmp_path / "shot.png")
    outdir = tmp_path / "clean"
    assert exifwipe.main([str(tmp_path), "-o", str(outdir)]) == 0
    out = capsys.readouterr().out
    assert "2 processed, 1 skipped" in out
    assert "errors" not in out.split("done.")[1]
    assert_jpeg_clean((outdir / "photo.jpg").read_bytes())
    assert_png_clean((outdir / "shot.png").read_bytes())


def test_max_pixels_guard(tmp_path, capsys):
    img = Image.new("RGB", (64, 64))
    src = tmp_path / "big.jpg"
    img.save(src, format="JPEG")
    # limit below the image size -> refuse
    assert exifwipe.main([str(src), "--max-pixels", "1000"]) == 3
    err = capsys.readouterr().err
    assert "refusing" in err
    # with a generous limit it works
    assert exifwipe.main([str(src), "--max-pixels", "0"]) == 0
