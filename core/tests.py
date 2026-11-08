"""Pruebas de los criterios de aceptación principales de la ERS."""
import json
import threading
from datetime import time, timedelta
from decimal import Decimal

from django.core import mail
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from abordaje import servicios as abordaje_srv
from abordaje.models import RegistroAbordaje
from cuentas.models import CodigoRecuperacion, Rol, Usuario
from operacion import servicios as operacion_srv
from operacion.models import GrupoPropietarios, Lancha, PuntoEmbarque, Ruta, Viaje
from pagos import pasarela, servicios as pagos_srv
from pagos.models import Pago
from reembolsos import servicios as reembolsos_srv
from reembolsos.models import SolicitudReembolso
from reservas import servicios as reservas_srv
from reservas.models import Reserva, Tiquete

CLAVE = "Lancha*Segura2026"


def pasajeros(n, base="1000"):
    return [{"nombre": f"Pasajero {i}", "tipo_documento": "CC", "documento": f"{base}{i}", "telefono": ""} for i in range(n)]


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ruta = Ruta.objects.create(nombre="Buenaventura – Timbiquí")
        cls.bun = PuntoEmbarque.objects.create(ruta=cls.ruta, nombre="Muelle BUN", ciudad="Buenaventura")
        cls.tim = PuntoEmbarque.objects.create(ruta=cls.ruta, nombre="Muelle TIM", ciudad="Timbiquí")
        cls.grupo = GrupoPropietarios.objects.create(nombre="Grupo 1")
        cls.lancha = Lancha.objects.create(nombre="L1", matricula="M-1", capacidad_autorizada=3, grupo=cls.grupo)
        cls.lancha2 = Lancha.objects.create(nombre="L2", matricula="M-2", capacidad_autorizada=20, grupo=cls.grupo)
        mk = lambda email, rol: Usuario.objects.create_user(email, CLAVE, nombre=rol.label, rol=rol, identificacion="1", telefono="3")
        cls.pasajero = mk("p@x.co", Rol.PASAJERO)
        cls.otro = mk("otro@x.co", Rol.PASAJERO)
        cls.ventas = mk("v@x.co", Rol.VENTAS)
        cls.abordaje = mk("a@x.co", Rol.ABORDAJE)
        cls.operador = mk("o@x.co", Rol.OPERADOR)
        cls.admin = mk("ad@x.co", Rol.ADMIN)

    def nuevo_viaje(self, **kw):
        datos = dict(
            ruta=self.ruta, sentido=Viaje.Sentido.IDA, punto_embarque=self.bun, punto_desembarque=self.tim,
            fecha=timezone.localdate() + timedelta(days=2), hora_programada=time(7, 0), tarifa=Decimal(160000),
            lancha=self.lancha, cupos=3, habilitado=True,
        )
        datos.update(kw)
        return Viaje.objects.create(**datos)

    def setUp(self):
        self.viaje = self.nuevo_viaje()

    def cliente(self, usuario):
        c = Client()
        c.force_login(usuario)
        return c

    def reserva_pagada(self, n=1, usuario=None):
        r = reservas_srv.crear_reserva(usuario or self.pasajero, self.viaje.pk, pasajeros(n), True)
        pagos_srv.registrar_pago_efectivo(r, r.total, self.ventas)
        r.refresh_from_db()
        return r


class CuentasTests(Base):
    def test_registro_activo_inmediato_y_correo(self):  # RF-COM-01 CA3, CA4
        resp = self.client.post(reverse("cuentas:registro"), {
            "nombre": "Ana Ríos", "tipo_documento": "CC", "identificacion": "123", "telefono": "300", "email": "Ana@Correo.co",
            "acepta_terminos": "on", "password1": CLAVE, "password2": CLAVE,
        })
        self.assertRedirects(resp, reverse("reservas:buscar"))
        u = Usuario.objects.get(email="ana@correo.co")
        self.assertTrue(u.is_active)
        self.assertIsNotNone(u.acepto_terminos_en)
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)
        self.assertEqual(len(mail.outbox), 1)

    def test_registro_exige_terminos_y_correo_unico(self):  # CA1, CA2, CA5
        datos = {"nombre": "X", "tipo_documento": "CC", "identificacion": "1", "telefono": "1", "email": "p@x.co",
                 "password1": CLAVE, "password2": CLAVE}
        resp = self.client.post(reverse("cuentas:registro"), datos)
        self.assertContains(resp, "Ya existe una cuenta")
        self.assertContains(resp, "Debe aceptar los términos")
        datos.update(email="no-es-correo")
        resp = self.client.post(reverse("cuentas:registro"), datos)
        self.assertEqual(Usuario.objects.filter(nombre="X").count(), 0)

    def test_login_mensaje_generico(self):  # RF-COM-02 CA1
        r1 = self.client.post(reverse("cuentas:login"), {"email": "p@x.co", "password": "mala"}, follow=True)
        r2 = self.client.post(reverse("cuentas:login"), {"email": "noexiste@x.co", "password": "mala"}, follow=True)
        self.assertContains(r1, "Correo o contraseña incorrectos.")
        self.assertContains(r2, "Correo o contraseña incorrectos.")

    def test_pasajero_bloqueado_en_modulos_administrativos(self):  # RF-COM-02 CA2, RNF-03
        c = self.cliente(self.pasajero)
        for nombre in ["operacion:panel", "pagos:taquilla", "abordaje:inicio", "reportes:reportes", "operacion:configuracion",
                       "cuentas:personal_lista"]:
            self.assertEqual(c.get(reverse(nombre)).status_code, 403, nombre)
        self.assertEqual(c.get(reverse("operacion:panel")).status_code, 403)

    def test_admin_hereda_operador_pero_no_taquilla(self):
        c = self.cliente(self.admin)
        self.assertEqual(c.get(reverse("operacion:panel")).status_code, 200)
        self.assertEqual(c.get(reverse("reportes:reportes")).status_code, 200)
        self.assertEqual(c.get(reverse("pagos:taquilla")).status_code, 403)
        self.assertEqual(self.cliente(self.operador).get(reverse("operacion:configuracion")).status_code, 403)

    def test_recuperacion_con_codigo(self):  # RF-COM-02 CA3, CA4
        self.client.post(reverse("cuentas:recuperar"), {"email": "p@x.co"})
        codigo = mail.outbox[-1].body.split("es: ")[1][:6]
        nueva = "OtraClave*2026"
        resp = self.client.post(reverse("cuentas:recuperar_confirmar"), {"email": "p@x.co", "codigo": "000000" if codigo != "000000" else "111111", "password1": nueva, "password2": nueva})
        self.assertContains(resp, "no es válido")
        resp = self.client.post(reverse("cuentas:recuperar_confirmar"), {"email": "p@x.co", "codigo": codigo, "password1": nueva, "password2": nueva})
        self.assertRedirects(resp, reverse("cuentas:login"))
        self.pasajero.refresh_from_db()
        self.assertTrue(self.pasajero.check_password(nueva))
        self.assertFalse(CodigoRecuperacion.objects.filter(usuario=self.pasajero, usado=False).exists())

    def test_admin_crea_personal(self):  # CU-17, RF-IN-03
        c = self.cliente(self.admin)
        resp = c.post(reverse("cuentas:personal_crear"), {"nombre": "Nuevo", "email": "n@x.co", "tipo_documento": "CC", "identificacion": "9", "telefono": "1", "rol": Rol.ABORDAJE})
        self.assertRedirects(resp, reverse("cuentas:personal_lista"))
        self.assertEqual(Usuario.objects.get(email="n@x.co").rol, Rol.ABORDAJE)
        self.assertIn("código", mail.outbox[-1].body)
        resp = c.post(reverse("cuentas:personal_crear"), {"nombre": "Dup", "email": "N@x.co", "tipo_documento": "CC", "rol": Rol.VENTAS})
        self.assertContains(resp, "Correo ya registrado")


class ViajesTests(Base):
    def test_busqueda_solo_habilitados(self):  # RF-PAS-01
        self.nuevo_viaje(habilitado=False, lancha=self.lancha2, hora_programada=time(9, 0), cupos=20)
        resp = self.client.get(reverse("reservas:buscar"), {"origen": "Buenaventura", "destino": "Timbiquí", "fecha": self.viaje.fecha})
        self.assertEqual(len(resp.context["resultados"]), 1)
        resp = self.client.get(reverse("reservas:buscar"), {"origen": "Timbiquí", "destino": "Buenaventura", "fecha": self.viaje.fecha})
        self.assertContains(resp, "Sin disponibilidad")
        resp = self.client.get(reverse("reservas:buscar"), {"origen": "Buenaventura", "destino": "", "fecha": ""})
        self.assertIsNone(resp.context["resultados"])

    def test_cupos_no_superan_capacidad(self):  # RF-ADM-01 CA3, RF-IN-02 CA2
        c = self.cliente(self.operador)
        resp = c.post(reverse("operacion:viaje_nuevo"), {
            "ruta": self.ruta.pk, "sentido": "REGRESO", "punto_embarque": self.tim.pk, "punto_desembarque": self.bun.pk,
            "fecha": self.viaje.fecha, "hora_programada": "08:00", "tarifa": 160000, "lancha": self.lancha.pk, "cupos": 50,
        })
        self.assertContains(resp, "superan la capacidad autorizada")
        resp = c.post(reverse("operacion:viaje_nuevo"), {
            "ruta": self.ruta.pk, "sentido": "REGRESO", "punto_embarque": self.tim.pk, "punto_desembarque": self.bun.pk,
            "fecha": self.viaje.fecha, "hora_programada": "08:00", "tarifa": 160000, "lancha": self.lancha.pk, "cupos": "",
        })
        v = Viaje.objects.get(sentido="REGRESO")
        self.assertEqual(v.cupos, 3)
        self.assertEqual(v.creado_por, self.operador)
        self.assertTrue(v.cambios.exists())  # CA2 auditoría

    def test_lancha_no_disponible(self):  # CU-12 excepción
        v = Viaje(ruta=self.ruta, sentido="IDA", punto_embarque=self.bun, punto_desembarque=self.tim, fecha=self.viaje.fecha,
                  hora_programada=time(10, 0), tarifa=1, lancha=self.lancha, cupos=1)
        with self.assertRaises(Exception):
            v.full_clean()

    def test_hora_efectiva_se_refleja(self):  # RF-ADM-02 CA2/CA3
        r = self.reserva_pagada()
        operacion_srv.ajustar_hora_efectiva(self.viaje, time(9, 30), "Marea baja", self.operador)
        t = Tiquete.objects.get(pasajero__reserva=r)
        self.assertEqual(t.viaje.hora_vigente, time(9, 30))
        self.assertEqual(t.viaje.hora_programada, time(7, 0))
        resp = self.client.get(reverse("reservas:api_viajes"), {"origen": "Buenaventura", "destino": "Timbiquí", "fecha": self.viaje.fecha})
        self.assertEqual(resp.json()["viajes"][0]["hora"], "09:30")


class ReservasTests(Base):
    def test_reserva_bloquea_cupos_y_codigo_unico(self):  # RF-PAS-02
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(2), True)
        self.viaje.refresh_from_db()
        self.assertEqual(self.viaje.cupos_disponibles, 1)
        self.assertEqual(r.usuario, self.pasajero)
        self.assertTrue(r.codigo.startswith("R-"))
        with self.assertRaisesMessage(reservas_srv.ErrorReserva, "Cupos insuficientes"):
            reservas_srv.crear_reserva(self.otro, self.viaje.pk, pasajeros(2, "2000"), True)

    def test_idempotencia(self):  # RNF-08
        a = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), True, clave_idempotencia="abc")
        b = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), True, clave_idempotencia="abc")
        self.assertEqual(a.pk, b.pk)
        self.viaje.refresh_from_db()
        self.assertEqual(self.viaje.cupos_ocupados, 1)

    def test_vencimiento_libera_cupos(self):  # CU-04 excepción
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(3), True)
        Reserva.objects.filter(pk=r.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        self.assertEqual(reservas_srv.expirar_reservas(), 1)
        self.viaje.refresh_from_db()
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.VENCIDA)
        self.assertEqual(self.viaje.cupos_disponibles, 3)
        with self.assertRaises(pagos_srv.ErrorPago):
            pagos_srv.registrar_pago_efectivo(r, r.total, self.ventas)

    def test_no_se_vende_sin_politica_ni_viaje_deshabilitado(self):
        with self.assertRaises(reservas_srv.ErrorReserva):
            reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), False)
        v = self.nuevo_viaje(habilitado=False, lancha=self.lancha2, cupos=5, hora_programada=time(8, 0))
        with self.assertRaises(reservas_srv.ErrorReserva):
            reservas_srv.crear_reserva(self.pasajero, v.pk, pasajeros(1), True)

    def test_vista_reservar(self):
        c = self.cliente(self.pasajero)
        datos = {"p-TOTAL_FORMS": 2, "p-INITIAL_FORMS": 0, "p-MIN_NUM_FORMS": 1, "p-MAX_NUM_FORMS": 10,
                 "p-0-nombre": "A", "p-0-tipo_documento": "CC", "p-0-documento": "11",
                 "p-1-nombre": "B", "p-1-tipo_documento": "TI", "p-1-documento": "22",
                 "acepta_politica": "on", "clave_idempotencia": "k1"}
        resp = c.post(reverse("reservas:reservar", args=[self.viaje.pk]), datos)
        r = Reserva.objects.get()
        self.assertRedirects(resp, reverse("reservas:detalle", args=[r.codigo]))
        self.assertEqual(r.cantidad, 2)
        self.assertEqual(self.cliente(self.otro).get(reverse("reservas:detalle", args=[r.codigo])).status_code, 404)


class ConcurrenciaTests(TransactionTestCase):
    """RNF-07: peticiones simultáneas sobre el último cupo."""

    def test_ultimo_cupo(self):
        if connection.vendor == "sqlite" and connection.settings_dict["NAME"].startswith("file:memorydb"):
            pass  # SQLite en memoria comparte conexión por hilo; la actualización condicional sigue siendo atómica.
        ruta = Ruta.objects.create(nombre="R")
        p1 = PuntoEmbarque.objects.create(ruta=ruta, nombre="A", ciudad="Buenaventura")
        p2 = PuntoEmbarque.objects.create(ruta=ruta, nombre="B", ciudad="Timbiquí")
        lancha = Lancha.objects.create(nombre="L", matricula="X", capacidad_autorizada=1)
        viaje = Viaje.objects.create(ruta=ruta, punto_embarque=p1, punto_desembarque=p2, fecha=timezone.localdate() + timedelta(days=1),
                                     hora_programada=time(7), tarifa=1, lancha=lancha, cupos=1, habilitado=True)
        usuarios = [Usuario.objects.create_user(f"u{i}@x.co", CLAVE, nombre="U") for i in range(6)]
        resultados = []

        def intentar(u):
            try:
                reservas_srv.crear_reserva(u, viaje.pk, pasajeros(1), True)
                resultados.append("ok")
            except reservas_srv.ErrorReserva:
                resultados.append("rechazada")
            except Exception as e:  # bloqueo de SQLite
                resultados.append(type(e).__name__)
            finally:
                connection.close()

        hilos = [threading.Thread(target=intentar, args=(u,)) for u in usuarios]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        viaje.refresh_from_db()
        self.assertEqual(resultados.count("ok"), 1, resultados)
        self.assertEqual(viaje.cupos_ocupados, 1)
        self.assertEqual(Reserva.objects.count(), 1)


class PagosTests(Base):
    def test_efectivo_confirma_y_emite(self):  # RF-PAG-01, RF-TIQ-01
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(2), True)
        c = self.cliente(self.ventas)
        resp = c.post(reverse("pagos:efectivo", args=[r.codigo]), {"valor_recibido": "400000"})
        pago = Pago.objects.get()
        self.assertRedirects(resp, reverse("pagos:comprobante", args=[pago.referencia]))
        self.assertEqual(pago.registrado_por, self.ventas)
        self.assertEqual(pago.cambio, 80000)
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(Tiquete.objects.filter(pasajero__reserva=r, estado="VALIDO").count(), 2)
        self.assertEqual(c.get(reverse("pagos:comprobante_pdf", args=[pago.referencia]))["Content-Type"], "application/pdf")

    def test_efectivo_solo_ventas(self):  # RF-PAG-01 CA4
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), True)
        for u in (self.pasajero, self.operador, self.admin, self.abordaje):
            self.assertEqual(self.cliente(u).post(reverse("pagos:efectivo", args=[r.codigo]), {"valor_recibido": "160000"}).status_code, 403)
        with self.assertRaises(pagos_srv.ErrorPago):
            pagos_srv.registrar_pago_efectivo(r, r.total, self.admin)

    def test_pago_en_linea_webhook(self):  # RF-PAG-02
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), True)
        c = self.cliente(self.pasajero)
        resp = c.post(reverse("pagos:pagar_en_linea", args=[r.codigo]))
        pago = Pago.objects.get()
        self.assertRedirects(resp, reverse("pagos:pasarela_simulada", args=[pago.referencia]))
        datos = {"referencia": pago.referencia, "estado": "APROBADO", "transaccion": "TX-1", "valor": "160000"}
        malo = self.client.post(reverse("pagos:notificacion"), json.dumps(datos), content_type="application/json", HTTP_X_WALMAR_FIRMA="x")
        self.assertEqual(malo.status_code, 403)
        r.refresh_from_db()
        self.assertTrue(r.pendiente)
        for _ in range(2):  # notificación repetida: idempotente
            ok = self.client.post(reverse("pagos:notificacion"), json.dumps(datos), content_type="application/json",
                                  HTTP_X_WALMAR_FIRMA=pasarela.firmar(datos))
            self.assertEqual(ok.status_code, 200)
        pago.refresh_from_db()
        r.refresh_from_db()
        self.assertEqual(pago.estado, "APROBADO")
        self.assertEqual(pago.referencia_externa, "TX-1")
        self.assertTrue(r.confirmada)
        self.assertEqual(Tiquete.objects.filter(pasajero__reserva=r).count(), 1)

    def test_pago_rechazado_retiene_reserva(self):
        r = reservas_srv.crear_reserva(self.pasajero, self.viaje.pk, pasajeros(1), True)
        pago = pagos_srv.iniciar_pago_en_linea(r, self.pasajero)
        pagos_srv.procesar_notificacion({"referencia": pago.referencia, "estado": "RECHAZADO", "transaccion": "T", "valor": "160000"})
        r.refresh_from_db()
        self.assertTrue(r.pendiente)
        self.assertFalse(Tiquete.objects.exists())  # RF-TIQ-01 CA3

    def test_tiquete_pdf_y_acceso(self):
        r = self.reserva_pagada()
        t = Tiquete.objects.get(pasajero__reserva=r)
        c = self.cliente(self.pasajero)
        self.assertEqual(c.get(reverse("reservas:tiquete_pdf", args=[t.codigo]))["Content-Type"], "application/pdf")
        self.assertContains(c.get(reverse("reservas:tiquete", args=[t.codigo])), "<svg")
        self.assertEqual(self.cliente(self.otro).get(reverse("reservas:tiquete", args=[t.codigo])).status_code, 404)


class AbordajeTests(Base):
    def test_validacion_y_reutilizacion(self):  # RF-ABO-01
        r = self.reserva_pagada()
        t = Tiquete.objects.get(pasajero__reserva=r)
        ok = abordaje_srv.validar_tiquete(t.codigo.lower(), self.viaje, self.abordaje)
        self.assertEqual(ok.resultado, "ACEPTADO")
        de_nuevo = abordaje_srv.validar_tiquete(t.codigo, self.viaje, self.abordaje)
        self.assertEqual(de_nuevo.resultado, "RECHAZADO")
        self.assertIn("ya utilizado", de_nuevo.motivo)
        self.assertEqual(abordaje_srv.validar_tiquete("WM-NOPE-NOPE", self.viaje, self.abordaje).resultado, "RECHAZADO")
        otro = self.nuevo_viaje(lancha=self.lancha2, cupos=10, hora_programada=time(12, 0), sentido="REGRESO", punto_embarque=self.tim, punto_desembarque=self.bun)
        r2 = reservas_srv.crear_reserva(self.pasajero, otro.pk, pasajeros(1, "9"), True)
        pagos_srv.registrar_pago_efectivo(r2, r2.total, self.ventas)
        t2 = Tiquete.objects.get(pasajero__reserva=r2)
        self.assertIn("no corresponde", abordaje_srv.validar_tiquete(t2.codigo, self.viaje, self.abordaje).motivo)
        self.assertEqual(RegistroAbordaje.objects.count(), 4)  # se registran también los rechazos

    def test_sincronizacion_offline_sin_duplicados(self):  # RF-PWA-01, CU-19
        r = self.reserva_pagada(2)
        codigos = list(Tiquete.objects.filter(pasajero__reserva=r).values_list("codigo", flat=True))
        c = self.cliente(self.abordaje)
        manifiesto = c.get(reverse("abordaje:manifiesto_reducido", args=[self.viaje.pk])).json()
        self.assertEqual(len(manifiesto["tiquetes"]), 2)
        self.assertNotIn(r.pasajeros.first().documento, json.dumps(manifiesto))  # documento enmascarado
        ops = {"operaciones": [{"clave": "k1", "viaje": self.viaje.pk, "codigo": codigos[0], "fecha": timezone.now().isoformat()},
                               {"clave": "k2", "viaje": self.viaje.pk, "codigo": codigos[0], "fecha": timezone.now().isoformat()}]}
        url = reverse("abordaje:api_sincronizar")
        res1 = c.post(url, json.dumps(ops), content_type="application/json").json()["resultados"]
        res2 = c.post(url, json.dumps(ops), content_type="application/json").json()["resultados"]
        self.assertEqual([x["resultado"] for x in res1], ["ACEPTADO", "RECHAZADO"])
        self.assertEqual(res1, res2)
        self.assertEqual(RegistroAbordaje.objects.count(), 2)
        self.assertTrue(RegistroAbordaje.objects.filter(sin_conexion=True).exists())

    def test_manifiesto_permisos(self):  # CU-15
        self.reserva_pagada()
        self.assertEqual(self.cliente(self.ventas).get(reverse("abordaje:manifiesto", args=[self.viaje.pk])).status_code, 403)
        resp = self.cliente(self.operador).get(reverse("abordaje:manifiesto", args=[self.viaje.pk]))
        self.assertContains(resp, "Pagado")
        csv = self.cliente(self.abordaje).get(reverse("abordaje:manifiesto", args=[self.viaje.pk]), {"formato": "csv"})
        self.assertIn("Pasajero 0", csv.content.decode())


class CambiosYReembolsosTests(Base):
    def test_cancelacion_viaje(self):  # RF-ADM-03, CU-13
        pagada = self.reserva_pagada(1)
        pendiente = reservas_srv.crear_reserva(self.otro, self.viaje.pk, pasajeros(1, "5"), True)
        mail.outbox.clear()
        operacion_srv.cancelar_viaje(self.viaje, "Mal tiempo", self.operador)
        pagada.refresh_from_db()
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Reserva.Estado.CANCELADA)
        self.assertEqual(pagada.respuesta_cambio, Reserva.RespuestaCambio.PENDIENTE)
        self.assertFalse(Tiquete.objects.filter(pasajero__reserva=pagada, estado="VALIDO").exists())
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(self.viaje.cambios.filter(tipo="CANCELACION", motivo="Mal tiempo").exists())

    def test_reprogramacion_reemplaza_tiquetes_y_traslado(self):
        r = self.reserva_pagada(1)
        viejo = Tiquete.objects.get(pasajero__reserva=r)
        operacion_srv.reprogramar_viaje(self.viaje, self.viaje.fecha + timedelta(days=1), time(8, 0), "Mantenimiento", self.operador)
        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, "ANULADO")
        nuevo = viejo.reemplazado_por
        self.assertEqual(nuevo.estado, "VALIDO")
        cambio = self.viaje.cambios.get(tipo="REPROGRAMACION")
        self.assertEqual(cambio.datos_anteriores["hora_programada"], "07:00:00")
        destino = self.nuevo_viaje(lancha=self.lancha2, cupos=10, hora_programada=time(14, 0))
        reservas_srv.trasladar_reserva(r.pk, destino.pk, self.pasajero)
        r.refresh_from_db()
        self.viaje.refresh_from_db()
        self.assertEqual(r.viaje, destino)
        self.assertEqual(self.viaje.cupos_ocupados, 0)
        self.assertEqual(Tiquete.objects.filter(pasajero__reserva=r, estado="VALIDO").count(), 1)

    def test_flujo_reembolso(self):  # RF-DEV-01
        r = self.reserva_pagada(1)
        s = reembolsos_srv.crear_solicitud(r, self.pasajero, SolicitudReembolso.Tipo.DESISTIMIENTO, "No puedo viajar")
        self.assertEqual(s.estado, "RECIBIDA")
        with self.assertRaises(reembolsos_srv.ErrorSolicitud):
            reembolsos_srv.crear_solicitud(r, self.pasajero, "OTRO", "dup")
        with self.assertRaises(reembolsos_srv.ErrorSolicitud):
            reembolsos_srv.cambiar_estado(s, "APROBADA", self.operador, "", 100)  # exige justificación
        with self.assertRaises(reembolsos_srv.ErrorSolicitud):
            reembolsos_srv.cambiar_estado(s, "APROBADA", self.operador, "ok", 999999999)  # tope: valor pagado
        reembolsos_srv.cambiar_estado(s, "APROBADA", self.operador, "Aviso previo", Decimal(120000))
        r.refresh_from_db()
        self.viaje.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CANCELADA)
        self.assertEqual(self.viaje.cupos_ocupados, 0)
        reembolsos_srv.cambiar_estado(s, "REEMBOLSADA", self.operador, referencia="DEV-001")
        self.assertEqual(Pago.objects.get(reserva=r).estado, "REEMBOLSADO")
        self.assertEqual(list(s.historial.values_list("estado", flat=True)), ["RECIBIDA", "APROBADA", "REEMBOLSADA"])
        resp = self.cliente(self.pasajero).get(reverse("reembolsos:detalle", args=[s.pk]))
        self.assertContains(resp, "Reembolsada")


class ReportesYPaginasTests(Base):
    def test_reporte(self):  # RF-REP-01
        self.reserva_pagada(2)
        resp = self.cliente(self.operador).get(reverse("reportes:reportes"))
        self.assertEqual(resp.context["ventas"]["total"], 320000)
        self.assertEqual(resp.context["pasajes"], 2)
        vacio = self.cliente(self.operador).get(reverse("reportes:reportes"), {"desde": "2020-01-01", "hasta": "2020-01-02"})
        self.assertContains(vacio, "Sin datos en el periodo")

    def test_paginas_por_rol_cargan(self):
        r = self.reserva_pagada(1)
        rutas = {
            None: ["core:inicio", "reservas:buscar", "cuentas:login", "cuentas:registro", "core:terminos", "core:offline", "manifest", "service_worker"],
            self.pasajero: ["reservas:mis_reservas", "reembolsos:mis_solicitudes", "cuentas:perfil"],
            self.ventas: ["pagos:taquilla"],
            self.abordaje: ["abordaje:inicio", "abordaje:sin_conexion"],
            self.operador: ["operacion:panel", "operacion:viajes", "operacion:programacion", "reembolsos:bandeja", "reportes:reportes", "operacion:viaje_nuevo"],
            self.admin: ["operacion:configuracion", "cuentas:personal_lista", "reportes:auditoria", "cuentas:personal_crear"],
        }
        for usuario, nombres in rutas.items():
            c = self.cliente(usuario) if usuario else Client()
            for n in nombres:
                self.assertEqual(c.get(reverse(n)).status_code, 200, n)
        c = self.cliente(self.admin)
        for tipo in ["rutas", "puntos", "grupos", "lanchas", "horarios"]:
            self.assertEqual(c.get(reverse("operacion:config_lista", args=[tipo])).status_code, 200)
            self.assertEqual(c.get(reverse("operacion:config_nuevo", args=[tipo])).status_code, 200)
        self.assertEqual(c.get(reverse("operacion:viaje_detalle", args=[self.viaje.pk])).status_code, 200)
        self.assertEqual(self.cliente(self.pasajero).get(reverse("reservas:detalle", args=[r.codigo])).status_code, 200)
        self.assertEqual(self.cliente(self.abordaje).get(reverse("abordaje:validar", args=[self.viaje.pk])).status_code, 200)
