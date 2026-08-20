"""Contrato estático de navegación sin iniciar Streamlit ni requerir Secrets."""
import ast
from pathlib import Path


def test_entrypoint_tiene_renderizadores_de_roles_y_session_state_base():
    source=Path('streamlit_app.py').read_text()
    tree=ast.parse(source)
    funciones={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    assert {'render_login_personal','render_admin','render_casino','render_coordinacion','render_comensal'} <= funciones
    for clave in ['usuario','rut_actual','dias_sel','wizard_idx','pedidos','portal_actual']:
        assert f'"{clave}" not in st.session_state' in source
    for rol in ['Gerencia','Finanzas','AdminCasino','Cocina','Coordinacion']:
        assert rol in source


def test_todos_los_python_tienen_ast_valido():
    for archivo in Path('.').rglob('*.py'):
        ast.parse(archivo.read_text(),filename=str(archivo))
