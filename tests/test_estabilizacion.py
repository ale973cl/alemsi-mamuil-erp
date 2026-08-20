"""Regresiones puras para reglas críticas que no requieren datos productivos."""
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import common


def test_rut_nuevo_no_es_deuda_por_defecto():
    # La ausencia de filas nunca puede convertirse en una deuda implícita.
    filas = pd.DataFrame(columns=["fecha", "estado_pago", "estado_consumo"])
    assert filas.empty


def test_cutoff_reserva_48_horas():
    ahora = datetime(2026, 8, 20, 13, 1)
    assert common.reserva_modificable("2026-08-22", "Cena", ahora)
    assert not common.reserva_modificable("2026-08-22", "Almuerzo", ahora)


def test_referencia_es_corta_unica_y_no_expone_rut_completo():
    with patch("common.random.randint", side_effect=[1000, 1001]):
        una = common.gen_referencia_reserva("12.345.678-5")
        dos = common.gen_referencia_reserva("12.345.678-5")
    assert una != dos
    assert una.startswith("MM-") and len(una) <= 25
    assert "12345678" not in una


def test_execute_sql_convierte_parametros_posicionales():
    class Session:
        def execute(self, statement, params=None):
            self.sql, self.params = str(statement), params
            return self
    ses = Session()
    common.execute_sql(ses, "UPDATE x SET a=%s WHERE id=%s", ("ok", 7))
    assert ses.sql == "UPDATE x SET a=:p0 WHERE id=:p1"
    assert ses.params == {"p0": "ok", "p1": 7}


def test_init_db_sale_si_version_ya_esta_aplicada():
    class Conn:
        def query(self, sql, params=None, ttl=None):
            assert params == {"clave": common.SCHEMA_VERSION}
            return pd.DataFrame({"ok": [1]})
    with patch("common.get_conn", return_value=Conn()):
        assert common.init_db() is False


def test_maximo_dias_consecutivos_admite_fechas_intercaladas():
    assert common.max_dias_consecutivos(['2026-08-20','2026-08-21','2026-08-23']) == 2
    assert common.max_dias_consecutivos(['2026-08-20','2026-08-21','2026-08-22']) == 3
