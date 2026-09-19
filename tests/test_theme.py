"""تست‌های سیستم تم تیره/روشن و کنتراست رنگ‌ها."""

import pytest

from app.services.ui_state import UiStateStore
from app.ui.theme import (
    DARK,
    LIGHT,
    DARK_PALETTE,
    LIGHT_PALETTE,
    THEMES,
    contrast_ratio,
    normalise_theme,
    palette,
    stylesheet,
)

from tests.test_main_window import make_window


# --------------------------------------------------------------- لایه رنگ‌ها


def test_palettes_have_the_same_roles():
    assert set(DARK_PALETTE) == set(LIGHT_PALETTE)
    assert len(DARK_PALETTE) == 35


def test_stylesheet_contains_no_leftover_tokens():
    for theme in THEMES:
        output = stylesheet(theme)
        assert "@" not in output
        assert "{" in output and "}" in output


def test_the_two_themes_produce_different_stylesheets():
    assert stylesheet(DARK) != stylesheet(LIGHT)


def test_dark_theme_is_dark_and_light_theme_is_light():
    dark = stylesheet(DARK)
    light = stylesheet(LIGHT)

    assert DARK_PALETTE["window"] in dark
    assert LIGHT_PALETTE["window"] in light
    # تم روشن نباید پس‌زمینه تیره داشته باشد و برعکس.
    assert "#151922" not in light
    assert "#f3f5f9" not in dark


def test_text_on_surface_contrast_meets_wcag_in_both_themes():
    for pal in (DARK_PALETTE, LIGHT_PALETTE):
        assert contrast_ratio(pal["textPrimary"], pal["surface"]) >= 4.5
        assert contrast_ratio(pal["textBody"], pal["surface"]) >= 4.5
        assert contrast_ratio(pal["textPrimary"], pal["window"]) >= 4.5
        assert contrast_ratio(pal["onAccent"], pal["accent"]) >= 4.5
        assert contrast_ratio(pal["warningText"], pal["warningBg"]) >= 4.5
        assert contrast_ratio(pal["dangerText"], pal["dangerBg"]) >= 4.5


def test_normalise_theme_falls_back_to_dark():
    assert normalise_theme("light") == LIGHT
    assert normalise_theme("LIGHT") == LIGHT
    assert normalise_theme("dark") == DARK
    assert normalise_theme("neon") == DARK
    assert normalise_theme("") == DARK
    assert normalise_theme(None) == DARK


def test_palette_rejects_unknown_theme():
    assert palette("neon") == DARK_PALETTE
    assert palette(LIGHT) == LIGHT_PALETTE


# ------------------------------------------------------------ ذخیره وضعیت تم


def test_ui_state_round_trips_the_theme(tmp_path):
    store = UiStateStore(tmp_path / "ui.json")

    assert store.theme() == DARK  # پیش‌فرض

    store.save_theme(LIGHT)
    assert UiStateStore(tmp_path / "ui.json").theme() == LIGHT

    # مقدار خراب در فایل به تم تیره برمی‌گردد، برنامه نمی‌شکند.
    (tmp_path / "ui.json").write_text('{"theme": "solarized"}', encoding="utf-8")
    assert store.theme() == DARK


# ------------------------------------------------------------ رفتار پنجره اصلی


def test_window_starts_with_the_dark_theme(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)

    assert window.current_theme == DARK
    assert DARK_PALETTE["window"] in window.styleSheet()

    window.close()


def test_switch_theme_updates_style_and_persists(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()

    window.switch_theme(LIGHT)

    assert window.current_theme == LIGHT
    assert LIGHT_PALETTE["window"] in window.styleSheet()
    assert DARK_PALETTE["window"] not in window.styleSheet()
    assert window.ui_state.theme() == LIGHT

    # پنجره تازه تم ذخیره‌شده را می‌گیرد.
    reopened = make_window(qt_app, tmp_path, monkeypatch, ui_state=window.ui_state)
    assert reopened.current_theme == LIGHT
    reopened.close()

    window.close()


def test_switch_to_the_same_theme_is_a_no_op(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.switch_theme(DARK)
    assert window.current_theme == DARK

    # تم نامعتبر هم نادیده گرفته می‌شود.
    window.switch_theme("neon")
    assert window.current_theme == DARK

    window.close()


def test_settings_page_theme_combo_applies_immediately(qt_app, tmp_path, monkeypatch):
    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()
    window.show_page("settings")
    page = window.settings_page

    # کمبو با تم فعلی پنجره همگام است.
    assert page.theme_combo.currentData() == DARK

    # تغییر کمبو، پنجره را بلافاصله عوض می‌کند (بدون نیاز به ذخیره).
    page.theme_combo.setCurrentIndex(page.theme_combo.findData(LIGHT))

    assert window.current_theme == LIGHT
    assert window.ui_state.theme() == LIGHT
    assert page.theme_combo.currentData() == LIGHT

    window.close()


def test_window_renders_dark_then_light_pixelperfect(qt_app, tmp_path, monkeypatch):
    """وارسی پیکسلی: پشت‌زمینه واقعی رندرشده در هر دو تم درست است."""
    from PySide6.QtGui import QImage

    window = make_window(qt_app, tmp_path, monkeypatch)
    window.show()
    window.resize(900, 600)

    def render():
        qt_app.processEvents()
        image = QImage(900, 600, QImage.Format.Format_ARGB32)
        window.render(image)
        return image

    def pixel(image, x, y):
        color = image.pixelColor(x, y)
        return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"

    dark_image = render()
    # صفحه داشبورد خودش پس‌زمینه سطحی دارد؛ پس‌زمینه پنجره از کنار سایدبار و
    # شکاف چیدمان خوانده می‌شود. برای هر نقطه، یکی از دو سطح مجاز است.
    allowed_dark = {DARK_PALETTE["window"], DARK_PALETTE["surfaceSubtle"]}
    allowed_light = {LIGHT_PALETTE["window"], LIGHT_PALETTE["surfaceSubtle"]}
    assert pixel(dark_image, 30, 350) in allowed_dark  # سایدبار

    window.switch_theme(LIGHT)
    light_image = render()
    assert pixel(light_image, 30, 350) in allowed_light
    assert pixel(light_image, 450, 350) in allowed_light

    window.switch_theme(DARK)
    assert pixel(render(), 30, 350) in allowed_dark

    window.close()
