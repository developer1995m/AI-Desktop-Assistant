"""ساخت آیکون برنامه (PNG و ICO چنداندازه) با QPainter.

اجرا: .venv\\Scripts\\python.exe tools/make_icon.py

خروجی:
    assets/app_icon.png  (۲۵۶ پیکسل، برای پیش‌نمایش و مستندات)
    assets/app_icon.ico  (۲۵۶ تا ۱۶ پیکسل، برای پنجره، تسک‌بار و فایل exe)

آیکون به‌صورت کد ساخته می‌شود تا فایل دودویی بی‌توضیح در پروژه نماند و تغییر رنگ
برند فقط یک تغییر کوچک در همین فایل باشد.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

ICON_SIZES = (256, 128, 64, 48, 32, 16)
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

BACKDROP_TOP = QColor("#5f7cf6")
BACKDROP_BOTTOM = QColor("#3a4fca")
BUBBLE = QColor("#ffffff")
ACCENT = QColor("#9fe3c0")


def render_icon(size: int) -> QImage:
    """یک تصویر آیکون در اندازه داده‌شده می‌سازد."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # زمینه: مربع گرد با گرادیان عمودی.
    radius = size * 0.22
    backdrop = QRectF(0, 0, size, size)
    gradient = QLinearGradient(backdrop.topLeft(), backdrop.bottomLeft())
    gradient.setColorAt(0.0, BACKDROP_TOP)
    gradient.setColorAt(1.0, BACKDROP_BOTTOM)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(backdrop, radius, radius)

    # حباب گفتگو با دنباله کوچک پایین‌چپ.
    bubble = QPainterPath()
    bubble.addRoundedRect(
        QRectF(size * 0.20, size * 0.24, size * 0.60, size * 0.42),
        size * 0.13,
        size * 0.13,
    )
    tail = QPainterPath()
    tail.moveTo(size * 0.34, size * 0.64)
    tail.lineTo(size * 0.34, size * 0.78)
    tail.lineTo(size * 0.48, size * 0.64)
    tail.closeSubpath()
    bubble = bubble.united(tail)

    painter.setBrush(BUBBLE)
    painter.drawPath(bubble)

    # سه نقطه داخل حباب؛ در اندازه‌های کوچک به خط تبدیل می‌شوند تا محو نشوند.
    dot_radius = size * 0.045
    center_y = size * 0.45

    painter.setBrush(BACKDROP_BOTTOM)
    for index, ratio in enumerate((0.34, 0.50, 0.66)):
        painter.drawEllipse(
            QRectF(
                size * ratio - dot_radius,
                center_y - dot_radius,
                dot_radius * 2,
                dot_radius * 2,
            )
        )

    # یک نقطه تأکیدی کوچک بالا-راست، فقط در اندازه‌هایی که دیده می‌شود.
    if size >= 48:
        accent_radius = size * 0.055
        painter.setBrush(ACCENT)
        painter.drawEllipse(
            QRectF(
                size * 0.80 - accent_radius,
                size * 0.20 - accent_radius,
                accent_radius * 2,
                accent_radius * 2,
            )
        )

    painter.end()
    return image


def to_png_bytes(image: QImage) -> bytes:
    """تصویر را به داده PNG تبدیل می‌کند."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")

    return bytes(buffer.data())


def build_ico(images: list[QImage]) -> bytes:
    """فایل ICO چنداندازه از تصویرهای داده‌شده می‌سازد.

    قالب ICO در ویندوز از نسخه Vista ورودی‌های PNG را می‌پذیرد، پس هر اندازه به‌صورت
    PNG ذخیره می‌شود تا آیکون در هر بزرگ‌نمایی تمیز بماند.
    """
    payloads = [to_png_bytes(image) for image in images]

    header = struct.pack("<HHH", 0, 1, len(payloads))
    directory = b""
    offset = len(header) + 16 * len(payloads)

    for image, payload in zip(images, payloads):
        dimension = 0 if image.width() >= 256 else image.width()
        directory += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    return header + directory + b"".join(payloads)


def main() -> int:
    """آیکون‌ها را می‌سازد و مسیر خروجی‌ها را چاپ می‌کند."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    images = [render_icon(size) for size in ICON_SIZES]

    largest = images[0]
    png_path = ASSETS_DIR / "app_icon.png"
    ico_path = ASSETS_DIR / "app_icon.ico"

    if not largest.save(str(png_path), "PNG"):
        print(f"ساخت {png_path} ناموفق بود.", file=sys.stderr)
        return 1

    ico_path.write_bytes(build_ico(images))

    print(f"ساخته شد: {png_path} ({png_path.stat().st_size} بایت)")
    print(f"ساخته شد: {ico_path} ({ico_path.stat().st_size} بایت)")

    return 0


if __name__ == "__main__":
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    raise SystemExit(main())
