"""Generación de PDF: tiquetes con QR y comprobantes de pago."""
from io import BytesIO

from django.utils import timezone
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A6, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

AZUL = colors.HexColor("#0b4f6c")
GRIS = colors.HexColor("#5b6770")


def _qr(valor, tam):
    widget = QrCodeWidget(valor, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    d = Drawing(tam, tam, transform=[tam / (x2 - x1), 0, 0, tam / (y2 - y1), 0, 0])
    d.add(widget)
    return d


def qr_svg(valor, tam=220):
    return renderSVG.drawToString(_qr(valor, tam))


def _cop(valor):
    return "$" + f"{int(valor):,}".replace(",", ".") + " COP"


def tiquetes_pdf(tiquetes):
    buffer = BytesIO()
    tam = landscape(A6)
    c = canvas.Canvas(buffer, pagesize=tam)
    c.setTitle("Tiquetes WALMAR")
    ancho, alto = tam
    for t in tiquetes:
        viaje = t.viaje
        reserva = t.reserva
        c.setFillColor(AZUL)
        c.rect(0, alto - 16 * mm, ancho, 16 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(8 * mm, alto - 10.5 * mm, "WALMAR · Tiquete de lancha")
        c.setFont("Helvetica", 8)
        c.drawRightString(ancho - 8 * mm, alto - 10.5 * mm, f"Reserva {reserva.codigo}")

        c.setFillColor(colors.black)
        y = alto - 25 * mm
        c.setFont("Helvetica-Bold", 13)
        c.drawString(8 * mm, y, f"{viaje.origen}  →  {viaje.destino}")
        y -= 7 * mm
        filas = [
            ("Pasajero", t.pasajero.nombre),
            ("Documento", f"{t.pasajero.tipo_documento} {t.pasajero.documento_enmascarado}"),
            ("Fecha", viaje.fecha.strftime("%d/%m/%Y")),
            ("Hora de zarpe", viaje.hora_vigente.strftime("%H:%M") + ("  (ajustada)" if viaje.hora_cambiada else "")),
            ("Embarque", str(viaje.punto_embarque)),
            ("Lancha", f"{viaje.lancha.nombre} · {viaje.lancha.matricula}"),
            ("Valor", _cop(reserva.tarifa_unitaria)),
        ]
        for etiqueta, valor in filas:
            c.setFont("Helvetica", 7.5)
            c.setFillColor(GRIS)
            c.drawString(8 * mm, y, etiqueta.upper())
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.black)
            c.drawString(32 * mm, y, valor[:48])
            y -= 5.2 * mm

        qr = _qr(t.codigo, 40 * mm)
        from reportlab.graphics import renderPDF

        renderPDF.draw(qr, c, ancho - 47 * mm, alto - 63 * mm)
        c.setFont("Courier-Bold", 11)
        c.drawCentredString(ancho - 27 * mm, alto - 68 * mm, t.codigo)
        c.setFont("Helvetica", 7)
        c.setFillColor(GRIS)
        estado = t.get_estado_display()
        c.drawCentredString(ancho - 27 * mm, alto - 72 * mm, f"Estado: {estado}")
        c.drawString(
            8 * mm,
            6 * mm,
            "Preséntese con su documento antes de la hora de zarpe. Tiquete personal e intransferible.",
        )
        c.drawRightString(ancho - 8 * mm, 2.5 * mm, f"Emitido {timezone.localtime(t.emitido_en):%d/%m/%Y %H:%M}")
        c.showPage()
    c.save()
    return buffer.getvalue()


def comprobante_pdf(pago):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Comprobante {pago.referencia}")
    ancho, alto = A4
    reserva = pago.reserva
    c.setFillColor(AZUL)
    c.rect(0, alto - 30 * mm, ancho, 30 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, alto - 19 * mm, "WALMAR · Comprobante de pago")
    c.setFillColor(colors.black)
    y = alto - 45 * mm
    filas = [
        ("Comprobante", pago.referencia),
        ("Reserva", reserva.codigo),
        ("Medio de pago", pago.get_medio_display()),
        ("Estado", pago.get_estado_display()),
        ("Fecha y hora", timezone.localtime(pago.confirmado_en or pago.creado_en).strftime("%d/%m/%Y %H:%M")),
        ("Viaje", str(reserva.viaje)),
        ("Pasajes", str(reserva.cantidad)),
        ("Valor total", _cop(pago.valor)),
    ]
    if pago.valor_recibido is not None:
        filas += [("Valor recibido", _cop(pago.valor_recibido)), ("Cambio", _cop(pago.cambio))]
    if pago.referencia_externa:
        filas.append(("Ref. pasarela", pago.referencia_externa))
    if pago.registrado_por:
        filas.append(("Registrado por", pago.registrado_por.nombre))
    for etiqueta, valor in filas:
        c.setFont("Helvetica", 10)
        c.setFillColor(GRIS)
        c.drawString(20 * mm, y, etiqueta)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.black)
        c.drawString(65 * mm, y, valor)
        y -= 8 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Pasajeros")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for p in reserva.pasajeros.all():
        c.drawString(24 * mm, y, f"• {p.nombre} — {p.tipo_documento} {p.documento_enmascarado}")
        y -= 6 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(GRIS)
    c.drawString(20 * mm, 15 * mm, "Documento generado por WALMAR. Conserve este comprobante.")
    c.showPage()
    c.save()
    return buffer.getvalue()
