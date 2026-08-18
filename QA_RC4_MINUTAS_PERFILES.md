# ALEMSI v2.1.3.41-RC4

## Alcance
- Subbanner tornasol ALEMSI estandarizado para perfiles internos.
- Cocina mantiene un solo banner de perfil y sus módulos completos debajo.
- AdminCasino/AdminTotal cargan PDF original, revisan extracción y guardan minuta BORRADOR.
- Coordinación ve PDF original + minuta estructurada y puede Autorizar u Observar.
- Gerencia visualiza PDF/minuta y registra observaciones; no autoriza ni edita platos.
- CSV continúa como alternativa de carga masiva.
- Bodega, Reserva pública y common.py quedaron fuera del alcance y protegidos por comparación.

## Criterio de prueba
1. Cargar PDF desde AdminCasino.
2. Revisar/corregir filas extraídas y confirmar BORRADOR.
3. Corregir conflictos Opción 1/Opción 2.
4. Enviar a Coordinación.
5. Jorge debe ver PDF y minuta; observar.
6. AdminCasino corrige y reenvía.
7. Jorge autoriza.
8. Gerencia visualiza y puede registrar observación.
9. AdminCasino publica solo con autorización vigente.
