import secrets

# Sin caracteres ambiguos (0/O, 1/I/L).
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generar(prefijo="", longitud=8, bloques=4):
    cuerpo = "".join(secrets.choice(ALFABETO) for _ in range(longitud))
    partes = [cuerpo[i : i + bloques] for i in range(0, longitud, bloques)]
    return "-".join(([prefijo] if prefijo else []) + partes)


def normalizar(codigo):
    return (codigo or "").strip().upper().replace(" ", "")
