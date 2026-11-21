"""Saved application palettes; legacy light settings migrate to Monokai."""
import flet as ft


def apply_theme(page, choice):
    choice = 'monokai' if choice in ('light', 'monokai') else 'dark'
    page.theme_mode = ft.ThemeMode.DARK
    page.dark_theme = ft.Theme(color_scheme=ft.ColorScheme(
        primary='#A6E22E', on_primary='#202217',
        primary_container='#3D492A', on_primary_container='#E5F5C5',
        secondary='#66D9EF', on_secondary='#183238',
        secondary_container='#344449', on_secondary_container='#D4F2F6',
        tertiary='#FD971F', on_tertiary='#35240F',
        tertiary_container='#50402D', on_tertiary_container='#FFE4BE',
        error='#F58AA9', on_error='#451D2B',
        error_container='#593040', on_error_container='#FFDCE6',
        surface='#272822', on_surface='#F8F8F2', on_surface_variant='#D0CFC4',
        surface_dim='#22231E', surface_bright='#42433B',
        surface_container_lowest='#1E1F1A', surface_container_low='#2B2C26',
        surface_container='#30312B', surface_container_high='#373830',
        surface_container_highest='#404138',
        outline='#949587', outline_variant='#56574B',
        inverse_surface='#E7E5D8', on_inverse_surface='#272822', inverse_primary='#496A0C',
        shadow='#000000', scrim='#000000', surface_tint='#A6E22E',
    ), scaffold_bgcolor='#272822', canvas_color='#272822') if choice == 'monokai' else None
    return choice
