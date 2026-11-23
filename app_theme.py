"""Warm light palette with muted Monokai accents; preserve the default dark theme."""
import flet as ft


def apply_theme(page, choice):
    choice = 'light' if choice in ('light', 'monokai') else 'dark'
    page.theme_mode = ft.ThemeMode.LIGHT if choice == 'light' else ft.ThemeMode.DARK
    # Explicitly supply the dark theme: Flet otherwise inherits the light palette.
    page.dark_theme = ft.Theme()
    page.theme = ft.Theme(color_scheme=ft.ColorScheme(
        primary='#526B20', on_primary='#FFFFFF',
        primary_container='#DCE3BD', on_primary_container='#303C19',
        secondary='#216D77', on_secondary='#FFFFFF',
        secondary_container='#D0DFD9', on_secondary_container='#25454B',
        tertiary='#975519', on_tertiary='#FFFFFF',
        tertiary_container='#E9D5B6', on_tertiary_container='#543515',
        error='#A33352', on_error='#FFFFFF',
        error_container='#EFD2D7', on_error_container='#642334',
        surface='#EDE7D4', on_surface='#353B39', on_surface_variant='#565C55',
        surface_dim='#D9D4C2', surface_bright='#F2EDDD',
        surface_container_lowest='#F2EDDD', surface_container_low='#E9E3CF',
        surface_container='#E3DDCA', surface_container_high='#DDD7C3',
        surface_container_highest='#D5CFBA',
        outline='#797D6D', outline_variant='#B9B6A4',
        inverse_surface='#353B39', on_inverse_surface='#EDE7D4', inverse_primary='#B4CE78',
        shadow='#000000', scrim='#000000', surface_tint='#526B20',
    ), scaffold_bgcolor='#EDE7D4', canvas_color='#EDE7D4')
    return choice
