import re
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()


class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    n_tarjeta = db.Column(db.String(100), unique=True)
    n_solicitud = db.Column(db.String(100))
    nombre_completo = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(200))
    dni = db.Column(db.String(100))
    telefono = db.Column(db.String(100))
    articulo = db.Column(db.String(200))
    f_de_venta = db.Column(db.String(100))
    frecuencia_pago = db.Column(db.String(50))
    cond_de_venta = db.Column(db.String(100))
    referencia = db.Column(db.String(500))
    zona = db.Column(db.String(100))
    vendedora = db.Column(db.String(100))
    finalizado = db.Column(db.Boolean, default=False)

    pagos = db.relationship(
        'Pago',
        backref='cliente',
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==========================
    # PLANES DETALLADOS + ESTADO
    # ==========================
    def obtener_planes_detallados(self):
        if not self.cond_de_venta:
            return []

        # 🔥 CAMBIO: Permitimos que "+" también sea separador
        condicion_limpia = self.cond_de_venta.replace('+', '/')

        articulos = [a.strip() for a in (self.articulo or "").split('/')]
        planes_raw = [p.strip() for p in condicion_limpia.split('/')]

        # Preparar cálculo de fechas
        from datetime import datetime, timedelta
        import calendar

        fecha_venta = None
        frec = "mensual"

        if self.f_de_venta:
            try:
                f_str = str(self.f_de_venta).split(' ')[0]
                fecha_venta = datetime.strptime(f_str, '%Y-%m-%d')
            except:
                pass

        if self.frecuencia_pago:
            frec = str(self.frecuencia_pago).strip().lower()

        resultados = []

        for i, plan in enumerate(planes_raw):
            try:
                texto_limpio = plan.replace('.', '').replace(',', '').replace('$', '')
                numeros = re.findall(r'(\d+)', texto_limpio)

                if len(numeros) >= 2:
                    nombre_prod = articulos[i] if i < len(articulos) else f"Producto {i+1}"
                    cuotas_t = int(numeros[0])
                    valor_c = float(numeros[1])

                    tag = f"P{i+1}"
                    pagos_este_prod = [
                        p for p in self.pagos
                        if tag in (p.nota or "").upper()
                    ]

                    pagado = sum(p.monto for p in pagos_este_prod)
                    total_plan = cuotas_t * valor_c
                    pendiente = max(0, total_plan - pagado)
                    cant_pagas = len(pagos_este_prod)

                    estado = "PENDIENTE"
                    clase = "primary"
                    atraso = 0
                    proxima_venc = None

                    if pendiente <= 0:
                        estado = "FINALIZADO"
                        clase = "success"

                    elif fecha_venta:
                        fechas = []
                        f_iter = fecha_venta

                        for c in range(cuotas_t):
                            if c > 0:
                                if frec == 'semanal':
                                    f_iter += timedelta(days=7)
                                elif frec == 'quincenal':
                                    f_iter += timedelta(days=15)
                                elif frec == 'mensual':
                                    mes_n = f_iter.month - 1 + 1
                                    anio_n = f_iter.year + mes_n // 12
                                    mes_n = mes_n % 12 + 1
                                    dia_n = min(
                                        f_iter.day,
                                        calendar.monthrange(anio_n, mes_n)[1]
                                    )
                                    f_iter = f_iter.replace(
                                        year=anio_n,
                                        month=mes_n,
                                        day=dia_n
                                    )
                            fechas.append(f_iter)

                        hoy = datetime.now()
                        vencidas = sum(
                            1 for f in fechas if f.date() <= hoy.date()
                        )

                        atraso = max(0, vencidas - cant_pagas)

                        idx = cant_pagas if cant_pagas < len(fechas) else -1
                        proxima_venc = fechas[idx] if fechas else None

                        if atraso > 0:
                            estado = f"DEBE {atraso} CUOTA(S)"
                            clase = "danger"
                        else:
                            estado = "AL DÍA"
                            clase = "primary"

                    resultados.append({
                        'index': i + 1,
                        'nombre': nombre_prod,
                        'cuotas_t': cuotas_t,
                        'valor_c': valor_c,
                        'pagado': pagado,
                        'pendiente': pendiente,
                        'cuotas_pagas': cant_pagas,
                        'estado': estado,
                        'clase': clase,
                        'atraso': atraso,
                        'proxima': proxima_venc
                    })

            except Exception:
                continue

        return resultados

    def saldo_pendiente(self):
        return sum(p['pendiente'] for p in self.obtener_planes_detallados())

    # ==========================
    # 📅 INFO PAGOS (CALENDARIO REAL)
    # ==========================
    def info_pagos(self):
        if not self.f_de_venta or not self.frecuencia_pago:
            return None

        try:
            from datetime import datetime, timedelta
            import calendar

            def sumar_meses(fecha, meses):
                mes_nuevo = fecha.month - 1 + meses
                anio_nuevo = fecha.year + mes_nuevo // 12
                mes_nuevo = mes_nuevo % 12 + 1
                dia_nuevo = min(
                    fecha.day,
                    calendar.monthrange(anio_nuevo, mes_nuevo)[1]
                )
                return fecha.replace(
                    year=anio_nuevo,
                    month=mes_nuevo,
                    day=dia_nuevo
                )

            f_str = str(self.f_de_venta).split(' ')[0]
            fecha_venta = datetime.strptime(f_str, '%Y-%m-%d')
            hoy = datetime.now()
            frec = str(self.frecuencia_pago).strip().lower()

            planes = self.obtener_planes_detallados()
            if not planes:
                return None

            cuotas_pagas = planes[0]['cuotas_pagas']
            total_cuotas_plan = planes[0]['cuotas_t']

            fechas_vencimiento = []
            fecha_iter = fecha_venta

            for i in range(total_cuotas_plan):
                if i > 0:
                    if frec == 'semanal':
                        fecha_iter += timedelta(days=7)
                    elif frec == 'quincenal':
                        fecha_iter += timedelta(days=15)
                    elif frec == 'mensual':
                        fecha_iter = sumar_meses(fecha_iter, 1)

                fechas_vencimiento.append(fecha_iter)

            cuotas_que_deberian_estar_pagas = sum(
                1 for f in fechas_vencimiento if f.date() <= hoy.date()
            )

            atrasadas = max(
                0,
                cuotas_que_deberian_estar_pagas - cuotas_pagas
            )

            idx_proxima = cuotas_pagas

            if idx_proxima < len(fechas_vencimiento):
                proxima = fechas_vencimiento[idx_proxima]
            else:
                proxima = fechas_vencimiento[-1]

            return {
                'proxima': proxima,
                'atrasadas': int(atrasadas),
                'nro_cuota': min(cuotas_pagas + 1, total_cuotas_plan)
            }

        except Exception as e:
            print(f"Error calculando fechas: {e}")
            return None

    # ==========================
    # 🏭 ESTADO DETALLADO POR PRODUCTO
    # ==========================
    def estado_por_producto(self):
        if not self.f_de_venta or not self.frecuencia_pago:
            return []

        try:
            from datetime import datetime, timedelta
            import calendar

            f_str = str(self.f_de_venta).split(' ')[0]
            fecha_venta = datetime.strptime(f_str, '%Y-%m-%d')
            hoy = datetime.now()
            frec = str(self.frecuencia_pago).strip().lower()

            planes = self.obtener_planes_detallados()
            estados = []

            for plan in planes:
                fechas = []
                f_iter = fecha_venta

                for i in range(plan['cuotas_t']):
                    if i > 0:
                        if frec == 'semanal':
                            f_iter += timedelta(days=7)
                        elif frec == 'quincenal':
                            f_iter += timedelta(days=15)
                        elif frec == 'mensual':
                            mes_n = f_iter.month - 1 + 1
                            anio_n = f_iter.year + mes_n // 12
                            mes_n = mes_n % 12 + 1
                            dia_n = min(
                                f_iter.day,
                                calendar.monthrange(anio_n, mes_n)[1]
                            )
                            f_iter = f_iter.replace(
                                year=anio_n,
                                month=mes_n,
                                day=dia_n
                            )

                    fechas.append(f_iter)

                vencidas = sum(
                    1 for f in fechas if f.date() <= hoy.date()
                )

                pagas = plan['cuotas_pagas']
                atraso = max(0, vencidas - pagas)

                if plan['pendiente'] <= 0:
                    estado_str = "FINALIZADO"
                    clase = "success"
                elif atraso > 0:
                    estado_str = f"DEBE {atraso} CUOTA(S)"
                    clase = "danger"
                else:
                    estado_str = "AL DÍA"
                    clase = "primary"

                estados.append({
                    'nombre': plan['nombre'],
                    'estado': estado_str,
                    'clase': clase,
                    'atraso': atraso,
                    'proxima': fechas[pagas] if pagas < len(fechas) else fechas[-1]
                })

            return estados

        except:
            return []


class Pago(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monto = db.Column(db.Float)
    fecha = db.Column(db.DateTime, default=datetime.now)
    nota = db.Column(db.String(200))
    cliente_id = db.Column(
        db.Integer,
        db.ForeignKey('cliente.id'),
        nullable=False
    )


class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    nombre = db.Column(db.String(100), nullable=False)
    marca = db.Column(db.String(100))
    categoria = db.Column(db.String(100))
    cantidad = db.Column(db.Integer, default=0)
    imagen_url = db.Column(db.String(500))


class MovimientoStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'))
    
    # 🔥 ESTA LÍNEA ES LA QUE FALTABA PARA QUE NO DE ERROR EL HISTORIAL:
    producto = db.relationship('Producto', backref='movimientos')
    
    tipo = db.Column(db.String(50))
    cantidad = db.Column(db.Integer)
    fecha = db.Column(db.DateTime, default=datetime.now)
    detalle = db.Column(db.String(200))