"""تست‌های آیکون برنامه و ساختار فایل ICO."""

import struct

from app.ui import branding


def parse_ico(data: bytes) -> list[tuple[int, int, bytes]]:
    """فهرست (اندازه، طول، امضای داده) هر ورودی فایل ICO را برمی‌گرداند."""
    reserved, image_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert image_type == 1

    entries = []

    for index in range(count):
        start = 6 + index * 16
        width, height, _colors, _reserved, _planes, _bpp, length, offset = struct.unpack(
            "<BBBBHHII", data[start : start + 16]
        )
        entries.append((width or 256, length, data[offset : offset + 8]))
        assert width == height

    return entries


def test_icon_files_exist():
    assert branding.icon_path().is_file()
    assert (branding.icon_path().parent / "app_icon.png").is_file()


def test_png_preview_has_the_brand_size(qt_app):
    from PySide6.QtGui import QImage

    preview = QImage(str(branding.icon_path().parent / "app_icon.png"))

    assert preview.isNull() is False
    assert (preview.width(), preview.height()) == (256, 256)


def test_ico_contains_every_expected_size():
    entries = parse_ico(branding.icon_path().read_bytes())
    sizes = [size for size, _length, _head in entries]

    assert sizes == [256, 128, 64, 48, 32, 16]
    # هر ورودی باید PNG باشد؛ ویندوز از Vista به بعد آن را می‌پذیرد.
    assert all(head.startswith(b"\x89PNG\r\n\x1a\n") for _size, _length, head in entries)


def test_loaded_icon_reports_small_and_large_sizes(qt_app):
    icon = branding.load_app_icon()
    sizes = {(size.width(), size.height()) for size in icon.availableSizes()}

    assert icon.isNull() is False
    # تسک‌بار به اندازه کوچک و پنجره بند‌بند به اندازه بزرگ نیاز دارد.
    assert (16, 16) in sizes
    assert (256, 256) in sizes


def test_missing_icon_folder_yields_an_empty_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "resource_dir", lambda: tmp_path / "nowhere")

    icon = branding.load_app_icon()

    assert icon.isNull() is True
