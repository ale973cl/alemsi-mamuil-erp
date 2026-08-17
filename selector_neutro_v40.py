def selector_neutro(
    label,
    opciones,
    *,
    key,
    format_func=None,
    placeholder="— Seleccione —",
    disabled=False
):
    """Selector BD neutro: nunca selecciona automáticamente el primer registro."""
    lista = list(opciones or [])

    kwargs = {
        "index": None,
        "placeholder": placeholder,
        "key": key,
        "disabled": disabled,
    }

    if callable(format_func):
        kwargs["format_func"] = format_func

    return st.selectbox(label, lista, **kwargs)
