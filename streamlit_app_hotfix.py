"""ALEMSI v2.1.3.40 · HOTFIX SELECTORES

Entrada temporal y reversible para Streamlit Cloud.
No modifica datos ni ejecuta SQL adicional. Corrige compatibilidad con
Streamlit 1.61.x cuando un selectbox recibe format_func=None y luego carga
la aplicación oficial desde streamlit_app.py.
"""

import streamlit as st

_original_selectbox = st.selectbox


def _selectbox_compatible(*args, **kwargs):
    """No enviar format_func cuando su valor sea None."""
    if kwargs.get("format_func", "__NO_ENVIADO__") is None:
        kwargs.pop("format_func", None)
    return _original_selectbox(*args, **kwargs)


st.selectbox = _selectbox_compatible

# Carga la aplicación oficial. No duplica ni reemplaza su lógica.
import streamlit_app  # noqa: E402,F401
