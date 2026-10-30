"""Material accessibility labels for the explicit browser-test locale.

These expectations match pinned Flutter 3.44.0, not the host OS language.
Unsupported languages fail rather than accepting whichever label is present.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FlutterMaterialLabels:
    locale: str

    def __post_init__(self):
        if self.locale not in ('es', 'es-CL', 'en', 'en-US'):
            raise ValueError('Unsupported explicit Material test locale')

    @property
    def back(self):
        return 'Atrás' if self.locale.startswith('es') else 'Back'

    @property
    def open_navigation(self):
        return ('Abrir el menú de navegación' if self.locale.startswith('es')
                else 'Open navigation menu')

    def remaining(self, count):
        if type(count) is not int or count < 0:
            raise ValueError('Remaining character count must be a nonnegative integer')
        if self.locale.startswith('es'):
            formatted = f'{count:,}'.replace(',', '.')
            return 'Queda 1 carácter.' if count == 1 else f'Quedan {formatted} caracteres'
        if count == 0:
            return 'No characters remaining'
        return '1 character remaining' if count == 1 else f'{count:,} characters remaining'
