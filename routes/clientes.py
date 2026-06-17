from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify 
from flask_login import login_required
from models import db, Cliente, Producto, MovimientoStock, Pago
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import re
import pandas as pd
import os
import shutil
from sqlalchemy import text

clientes_bp = Blueprint('clientes', __name__)

# --- TRADUCTOR DE MESES ---
MESES = {
    '01': 'Enero', '02': 'Febrero', '03': 'Marzo', '04': 'Abril',
    '05': 'Mayo', '06': 'Junio', '07': 'Julio', '08': 'Agosto',
    '09': 'Septiembre', '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'
}

def obtener_nombre_mes(yyyy_mm):
    try:
        y, m = yyyy_mm.split('-')
        return f"{MESES.get(m, m)} {y}"
    except:
        return yyyy_mm



# --- CONTADOR Y VISTA PRINCIPAL ---
@clientes_bp.route('/clientes')
@login_required
def clientes():
    try:
        db.session.execute(text("ALTER TABLE cliente ADD COLUMN IF NOT EXISTS n_solicitud VARCHAR(100)"))
        db.session.execute(text("ALTER TABLE cliente ADD COLUMN IF NOT EXISTS frecuencia_pago VARCHAR(50)"))
        db.session.execute(text("ALTER TABLE cliente ADD COLUMN IF NOT EXISTS zona VARCHAR(100)"))
        db.session.commit()
    except:
        db.session.rollback()

    todos = Cliente.query.all()

    # 🔥 NUESTRO MAIDEN DE ZONAS OFICIALES
    zonas_oficiales = ['Bosques', 'Quilmes', '812', 'Springfield']

    # Limpieza de datos, frecuencia automática y normalización de zonas
    for c in todos:
        if c.n_solicitud is None:
            c.n_solicitud = ""
        
        # ⚡ LÓGICA DE ASIGNACIÓN AUTOMÁTICA DE ZONAS VEJAS Y NUEVAS
        zona_limpia = (c.zona or "").strip().title()
        if zona_limpia in zonas_oficiales:
            c.zona = zona_limpia  # Unifica "bosques"/"BOSQUES" -> "Bosques"
        else:
            c.zona = "Otras Zonas"  # El limbo seguro para lo que no coincida o esté vacío

        condicion = (c.cond_de_venta or "").upper()
        if not c.frecuencia_pago or c.frecuencia_pago == "":
            if "(S)" in condicion:
                c.frecuencia_pago = "Semanal"
            elif "(Q)" in condicion:
                c.frecuencia_pago = "Quincenal"
            elif "(M)" in condicion:
                c.frecuencia_pago = "Mensual"

    db.session.commit()

    # 🔥 1. EXTRAER MESES DISPONIBLES PARA EL FILTRO
    meses_set = set()
    for c in todos:
        if c.f_de_venta and len(str(c.f_de_venta)) >= 7:
            meses_set.add(str(c.f_de_venta)[:7]) # Extrae 'YYYY-MM'

    meses_lista = sorted(list(meses_set), reverse=True)
    meses_dict = {m: obtener_nombre_mes(m) for m in meses_lista}

    # 🔥 2. APLICAR FILTRO SI EL USUARIO LO PIDIÓ
    mes_filtro = request.args.get('mes')
    if mes_filtro:
        clientes_filtrados = [c for c in todos if str(c.f_de_venta).startswith(mes_filtro)]
    else:
        clientes_filtrados = todos

    cantidad_total = len(clientes_filtrados)
    now_date_venta = datetime.now().strftime('%Y-%m-%d')
    
    lista_productos = Producto.query.all() 

    # Definimos la lista fija que va a leer el select del HTML de clientes
    zonas_filtro = zonas_oficiales + ['Otras Zonas']

    return render_template(
        'clientes.html',
        clientes=clientes_filtrados,
        cantidad_total=cantidad_total,
        now_date_venta=now_date_venta,
        getattr=getattr,
        productos_stock=lista_productos,  
        meses_dict=meses_dict,            
        mes_filtro=mes_filtro,
        zonas_filtro=zonas_filtro         # 👈 ENVIAMOS LA LISTA FIJA AL HTML
    )


# --- EVENTOS DE COBRO ---
@clientes_bp.route('/clientes/eventos_cobro')
@login_required
def eventos_cobro():
    clientes = Cliente.query.all()
    eventos = []
    hoy = datetime.now().date()
    
    for c in clientes:
        if c.saldo_pendiente() > 0 and c.f_de_venta:
            try:
                fecha_venta = datetime.strptime(c.f_de_venta, '%Y-%m-%d').date()
                intervalo = 7 if c.frecuencia_pago == 'Semanal' else 15 if c.frecuencia_pago == 'Quincenal' else 30
                
                planes = c.obtener_planes_detallados()
                if not planes:
                    continue
                
                cuotas_pagas = planes[0]['cuotas_pagas']
                total_cuotas = planes[0]['cuotas_t']
                
                if cuotas_pagas < total_cuotas:
                    proxima = fecha_venta + timedelta(days=intervalo * (cuotas_pagas + 1))
                    
                    color = "#ff4757" if proxima < hoy else "#eccc68" if proxima == hoy else "#2ed573"
                    
                    eventos.append({
                        'title': f"{c.nombre_completo} (C.{cuotas_pagas + 1})",
                        'start': proxima.strftime('%Y-%m-%d'),
                        'color': color,
                        'textColor': '#000' if proxima == hoy else '#fff'
                    })
            except:
                continue

    return jsonify(eventos)

@clientes_bp.route('/clientes/guardar', methods=['POST'])
@login_required
def guardar_cliente():
    print("--- EMPEZANDO A GUARDAR ---")
    print("DATOS:", request.form)

    try:
        # 🔥 EL FIX ESTÁ ACÁ: Convertimos el ID vacío ("") a None
        c_id_raw = request.form.get('id', '').strip()
        c_id = int(c_id_raw) if c_id_raw.isdigit() else None

        n_tarjeta = request.form.get('n_tarjeta', '').strip()
        n_solicitud = request.form.get('n_solicitud', '').strip()

        # ==========================================
        # 🛡️ VALIDACIÓN 1: TARJETA OBLIGATORIA
        # ==========================================
        if not n_tarjeta:
            msg = "⚠️ Error: El N° de Tarjeta es obligatorio."
            productos_stock = Producto.query.all()

            if request.headers.get('HX-Request'):
                return render_template(
                    'fragmento_form.html',
                    error_msg=msg,
                    productos_stock=productos_stock,
                    now_date_venta=datetime.now().strftime('%Y-%m-%d'),
                    getattr=getattr
                )

            flash(msg)
            return redirect(url_for('clientes.clientes'))

        # ==========================================
        # 🛡️ VALIDACIÓN 2: TARJETA ÚNICA
        # ==========================================
        query_t = Cliente.query.filter(Cliente.n_tarjeta == n_tarjeta)
        if c_id is not None:
            query_t = query_t.filter(Cliente.id != c_id)
        cliente_existente = query_t.first()

        if cliente_existente:
            msg = f"⛔ ERROR: La Tarjeta {n_tarjeta} ya pertenece a {cliente_existente.nombre_completo}."
            productos_stock = Producto.query.all()

            if request.headers.get('HX-Request'):
                return render_template(
                    'fragmento_form.html',
                    error_msg=msg,
                    productos_stock=productos_stock,
                    now_date_venta=datetime.now().strftime('%Y-%m-%d'),
                    getattr=getattr
                )

            flash(msg)
            return redirect(url_for('clientes.clientes'))

        # ==========================================
        # 🛡️ VALIDACIÓN 3: SOLICITUD ÚNICA
        # ==========================================
        s_existe = None
        if n_solicitud:
            query_s = Cliente.query.filter(Cliente.n_solicitud == n_solicitud)
            if c_id is not None:
                query_s = query_s.filter(Cliente.id != c_id)
            s_existe = query_s.first()

        if s_existe:
            msg = f"⚠️ La Solicitud {n_solicitud} ya existe"
            productos_stock = Producto.query.all()

            if request.headers.get('HX-Request'):
                return render_template(
                    'fragmento_form.html',
                    error_msg=msg,
                    productos_stock=productos_stock,
                    now_date_venta=datetime.now().strftime('%Y-%m-%d'),
                    getattr=getattr
                )

            flash(msg)
            return redirect(url_for('clientes.clientes'))

        # ==========================================
        # RECOPILAMOS DATOS
        # ==========================================
        datos = {k: request.form.get(k, '') for k in [
            'n_tarjeta', 'n_solicitud', 'nombre_completo', 'direccion',
            'dni', 'telefono', 'f_de_venta', 'cond_de_venta',
            'referencia', 'frecuencia_pago', 'zona'
        ]}

        datos['articulo'] = request.form.get('articulo', '').strip()
        entrega_raw = request.form.get('entrega_inicial', '0')

        # ==========================================
        # LOGICA ANTI-FANTASMA 👻
        # ==========================================
        if c_id:
            cliente_check = Cliente.query.get(c_id)
            if not cliente_check:
                c_id = None

        # ==========================================
        # CREAR O ACTUALIZAR CLIENTE
        # ==========================================
        if not c_id:
            cliente_obj = Cliente(**datos)
            db.session.add(cliente_obj)
            db.session.flush()
            c_id = cliente_obj.id
        else:
            cliente_obj = Cliente.query.get(c_id)

            for key, value in datos.items():
                setattr(cliente_obj, key, value)

            Pago.query.filter(
                Pago.cliente_id == c_id,
                Pago.nota.like('%Entrega Inicial%')
            ).delete(synchronize_session=False)

        # ==========================================
        # PAGOS INICIALES
        # ==========================================
        if entrega_raw and entrega_raw.strip() not in ["0", ""]:
            try:
                if datos['f_de_venta']:
                    fecha_pago = datetime.strptime(datos['f_de_venta'], '%Y-%m-%d')
                else:
                    fecha_pago = datetime.now()
            except:
                fecha_pago = datetime.now()

            montos = [m.strip() for m in entrega_raw.replace(',', '/').split('/')]

            for i, monto_str in enumerate(montos):
                try:
                    monto_val = float(monto_str.replace('.', '') or 0)

                    if monto_val > 0:
                        db.session.add(Pago(
                            monto=monto_val,
                            nota=f"Entrega Inicial (P{i+1})",
                            fecha=fecha_pago,
                            cliente_id=cliente_obj.id
                        ))
                except:
                    continue

        # ==========================================
        # 🔻 DESCUENTO AUTOMÁTICO DE STOCK
        # ==========================================
        if not c_id_raw:
            articulo_nombre = datos['articulo']

            producto_stock = Producto.query.filter(
                Producto.nombre.ilike(f"%{articulo_nombre}%")
            ).first()

            if producto_stock:
                producto_stock.cantidad -= 1

                movimiento = MovimientoStock(
                    producto_id=producto_stock.id,
                    tipo='SALIDA',
                    cantidad=1,
                    fecha=datetime.now(),
                    detalle=f"Venta a: {cliente_obj.nombre_completo}"
                )

                db.session.add(movimiento)

                print(f"📉 Stock descontado: {producto_stock.nombre} (-1)")
            else:
                print("⚠️ No se encontró producto en stock con ese nombre.")

        # ==========================================
        # GUARDAR
        # ==========================================
        db.session.commit()
        flash("✅ Guardado con éxito.")

        # 👇 Primero HTMX
        if request.headers.get('HX-Request'):
            return "", 200, {'HX-Refresh': 'true'}

        # 👇 Después redirect normal
        return redirect(url_for('clientes.clientes'))

    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al guardar: {e}")
        return redirect(url_for('clientes.clientes'))


@clientes_bp.route('/clientes/tarjeta/<int:cliente_id>')
@login_required
def abrir_tarjeta(cliente_id):
    c = Cliente.query.get_or_404(cliente_id)
    # IMPORTANTE: Esto evita que falle la resta de días
    hoy_obj = datetime.now()
    hoy_str = hoy_obj.strftime('%Y-%m-%d')
    
    return render_template(
        'tarjeta.html', 
        cliente=c, 
        now_date=hoy_str, 
        now_date_obj=hoy_obj
    )



@clientes_bp.route('/clientes/formulario')
@login_required
def formulario_cliente():
    edit_id = request.args.get('edit')
    cliente_a_editar = Cliente.query.get(edit_id) if edit_id else None
    
    # 🔥 FIX CRÍTICO: Si el cliente tiene fecha con hora, la limpiamos SOLO para el formulario
    if cliente_a_editar and cliente_a_editar.f_de_venta:
        # Tomamos solo los primeros 10 caracteres (AAAA-MM-DD)
        cliente_a_editar.f_de_venta = str(cliente_a_editar.f_de_venta)[:10]

    now_date_venta = datetime.now().strftime('%Y-%m-%d')
    
    # Lógica de entrega inicial (sin cambios)
    entrega_str = ""
    if cliente_a_editar:
        pagos_ini = [str(int(p.monto)) for p in cliente_a_editar.pagos if "Entrega Inicial" in (p.nota or "")]
        if pagos_ini:
            entrega_str = " / ".join(pagos_ini)

    # 🔥 AGREGAR ESTA LÍNEA:
    lista_productos = Producto.query.all()

    return render_template(
        'fragmento_form.html',
        edit_cliente=cliente_a_editar,
        now_date_venta=now_date_venta,
        entrega_inicial_valor=entrega_str,
        getattr=getattr,
        productos_stock=lista_productos  # 👈 AGREGA ESTA LÍNEA
    )

# --- GUARDAR PAGO (FIX CRASH MODAL) ---
@clientes_bp.route('/tarjeta/<int:cliente_id>/pago/guardar', methods=['POST'])
@login_required
def guardar_pago(cliente_id):
    c = Cliente.query.get_or_404(cliente_id)

    monto = float(request.form['monto'])
    id_prod = request.form.get('id_producto_pago', 'P1')
    nota = f"{request.form.get('nota', 'Cuota')} ({id_prod})"
    fecha = datetime.strptime(request.form['fecha'], '%Y-%m-%d')

    db.session.add(Pago(
        monto=monto,
        nota=nota,
        fecha=fecha,
        cliente_id=cliente_id
    ))
    db.session.commit()

    hoy_obj = datetime.now()

    return render_template(
        'tarjeta.html',
        cliente=c,
        now_date=hoy_obj.strftime('%Y-%m-%d'),
        now_date_obj=hoy_obj
    )


# --- BORRAR CLIENTE ---
@clientes_bp.route('/clientes/borrar/<int:id>', methods=['DELETE', 'GET'])
@login_required
def borrar_cliente(id):
    c = Cliente.query.get(id)
    if c:
        db.session.delete(c)
        db.session.commit()

    return "", 200, {'HX-Trigger': 'clienteEliminado'}


# --- BORRAR PAGO ---
@clientes_bp.route('/pago/borrar/<int:id>')
@login_required
def borrar_pago(id):
    pago = Pago.query.get(id)
    if pago:
        c_id = pago.cliente_id
        db.session.delete(pago)
        db.session.commit()

        c = Cliente.query.get(c_id)
        hoy_obj = datetime.now()

        return render_template(
            'tarjeta.html',
            cliente=c,
            now_date=hoy_obj.strftime('%Y-%m-%d'),
            now_date_obj=hoy_obj
        )

    return "", 200


# --- EXPORTAR ---
@clientes_bp.route('/exportar')
@login_required
def exportar():
    clientes_list = Cliente.query.all()
    data = []

    for c in clientes_list:
        data.append({
            'N TARJETA': c.n_tarjeta,
            'N SOLICITUD': c.n_solicitud,
            'NOMBRE COMPLETO': c.nombre_completo,
            'DNI': c.dni,
            'TELEFONO': c.telefono,
            'DIRECCION': c.direccion,
            'ZONA': c.zona,
            'ARTICULO': c.articulo,
            'CONDICION': c.cond_de_venta,
            'FRECUENCIA': c.frecuencia_pago,
            'FECHA VENTA': c.f_de_venta,
            'REFERENCIA': c.referencia
        })

    df = pd.DataFrame(data)
    df.to_excel("ultimo_backup.xlsx", index=False)

    return send_file("ultimo_backup.xlsx", as_attachment=True)


# --- BORRAR TODO ---
@clientes_bp.route('/clientes/borrar_todo', methods=['POST'])
@login_required
def borrar_todo():
    try:
        db.session.query(Pago).delete()
        db.session.query(Cliente).delete()
        db.session.commit()
        flash("🔥 Base de datos vaciada por completo.")
    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Error al borrar: {e}")

    return redirect(url_for('clientes.clientes'))


# --- REESTABLECER ---
@clientes_bp.route('/clientes/reestablecer', methods=['POST'])
@login_required
def reestablecer():
    if not os.path.exists("ultima_importacion.xlsx"):
        flash("⚠️ No hay ninguna importación previa.")
        return redirect(url_for('clientes.clientes'))

    try:
        db.session.query(Pago).delete()
        db.session.query(Cliente).delete()

        df = pd.read_excel("ultima_importacion.xlsx")

        for _, row in df.iterrows():
            nuevo = Cliente(
                n_tarjeta=str(row.get('N TARJETA', '')).strip(),
                n_solicitud=str(row.get('N SOLICITUD', '')).strip(),
                nombre_completo=str(row.get('NOMBRE COMPLETO', '')).strip(),
                direccion=str(row.get('DIRECCION', '')).strip(),
                dni=str(row.get('DNI', '')).strip(),
                telefono=str(row.get('TELEFONO', '')).strip(),
                articulo=str(row.get('ARTICULO', '')).strip(),
                f_de_venta=str(row.get('FECHA VENTA', '')).strip(),
                cond_de_venta=str(row.get('CONDICION', '')).strip(),
                frecuencia_pago=str(row.get('FRECUENCIA', '')).strip(),
                zona=str(row.get('ZONA', '')).strip(),
                referencia=str(row.get('REFERENCIA', '')).strip()
            )
            db.session.add(nuevo)

        db.session.commit()
        flash("🔄 Reestablecido correctamente.")

    except Exception as e:
        db.session.rollback()
        flash(f"⚠️ Error: {e}")

    return redirect(url_for('clientes.clientes'))


# En clientes.py

@clientes_bp.route('/clientes/importar', methods=['POST'])
@login_required
def importar_clientes():
    file = request.files.get('file')
    if not file:
        flash("⚠️ No se seleccionó ningún archivo.")
        return redirect(url_for('clientes.clientes'))

    filename = file.filename.lower()
    
    try:
        # 🔥 DETECCIÓN INTELIGENTE DE FORMATO
        if filename.endswith('.csv'):
            # Leemos CSV (usando ; o , como separador automáticamente)
            try:
                df = pd.read_csv(file, sep=';', encoding='utf-8') # Prueba con punto y coma
                if len(df.columns) < 2: # Si falló, prueba con coma
                    file.seek(0)
                    df = pd.read_csv(file, sep=',', encoding='utf-8')
            except:
                file.seek(0)
                df = pd.read_csv(file, sep=',', encoding='latin-1') # Último intento encoding windows
                
        else:
            # Leemos Excel normal
            df = pd.read_excel(file)

        # Limpieza de datos (fillna para evitar errores de nan)
        df = df.fillna('')

        nuevos_cargados = 0
        errores = 0

        for _, row in df.iterrows():
            try:
                # 1. LIMPIEZA DE FECHA
                fecha_raw = str(row.get('FECHA VENTA', '')).strip()
                if ' ' in fecha_raw: 
                    fecha_raw = fecha_raw.split(' ')[0]
                if fecha_raw in ['nan', 'NaT', '']:
                    fecha_raw = None # Dejar None para que no rompa la base de datos

                # 2. FRECUENCIA
                frec = str(row.get('FRECUENCIA', '')).strip()
                if not frec or frec.lower() == 'nan':
                    frec = 'Semanal'

                # 3. REFERENCIA
                ref = str(row.get('REFERENCIA', '')).strip()
                if ref.lower() == 'nan': ref = ''
                
                # Verificamos si ya existe la tarjeta para no duplicar
                n_tarjeta = str(row.get('N TARJETA', '')).strip().replace('.0', '') # Quita el .0 de los números
                if not n_tarjeta: 
                    continue # Saltamos filas vacías
                
                existe = Cliente.query.filter_by(n_tarjeta=n_tarjeta).first()
                if existe:
                    continue # Si ya existe, lo saltamos (o podrías actualizarlo)

                nuevo = Cliente(
                    n_tarjeta=n_tarjeta,
                    n_solicitud=str(row.get('N SOLICITUD', '')).strip().replace('.0', ''),
                    nombre_completo=str(row.get('NOMBRE COMPLETO', '')).strip(),
                    direccion=str(row.get('DIRECCION', '')).strip(),
                    dni=str(row.get('DNI', '')).strip().replace('.0', ''),
                    telefono=str(row.get('TELEFONO', '')).strip().replace('.0', ''),
                    articulo=str(row.get('ARTICULO', '')).strip(),
                    f_de_venta=fecha_raw,
                    cond_de_venta=str(row.get('CONDICION', '')).strip(),
                    frecuencia_pago=frec,
                    zona=str(row.get('ZONA', '')).strip(),
                    referencia=ref
                )
                db.session.add(nuevo)
                nuevos_cargados += 1
                
            except Exception as e:
                print(f"Error en fila: {e}")
                errores += 1
                continue

        db.session.commit()
        
        if nuevos_cargados > 0:
            flash(f"✅ Se importaron {nuevos_cargados} clientes correctamente.")
        else:
            flash("⚠️ No se encontraron clientes nuevos o el archivo estaba vacío.")
            
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error crítico al importar: {str(e)}")

    return redirect(url_for('clientes.clientes'))

# --- FINALIZADOS ---
@clientes_bp.route('/clientes/finalizados')
@login_required
def finalizados():
    todos = Cliente.query.all()
    lista_finalizados = [c for c in todos if c.saldo_pendiente() <= 0 and len(c.pagos) > 0]

    return render_template('finalizados.html', clientes=lista_finalizados)


# --- RESUMEN DE VENTAS (NUEVO PANEL) ---
# --- RESUMEN Y DASHBOARD CENTRAL ---
# --- RESUMEN Y DASHBOARD CENTRAL ---
@clientes_bp.route('/resumen')
@login_required
def resumen():
    todos = Cliente.query.all()

    # 1. Extraemos meses para el filtro
    meses_set = set()
    for c in todos:
        if c.f_de_venta and len(str(c.f_de_venta)) >= 7:
            meses_set.add(str(c.f_de_venta)[:7])
    
    meses_lista = sorted(list(meses_set), reverse=True)
    meses_dict = {m: obtener_nombre_mes(m) for m in meses_lista}

    # 2. Aplicamos filtro
    mes_filtro = request.args.get('mes')
    if mes_filtro:
        clientes_filtrados = [c for c in todos if str(c.f_de_venta).startswith(mes_filtro)]
    else:
        clientes_filtrados = todos

    # 3. CONTEO INTELIGENTE Y EXACTO DE PRODUCTOS
    from collections import Counter
    import re
    conteo = Counter()
    
    for c in clientes_filtrados:
        art_raw = str(c.articulo or "").strip().upper()
        
        # Ignorar vacíos absolutos
        if not art_raw or art_raw in ["-", "NAN", "NONE"]:
            continue
            
        # 🔥 Separamos por si escribiste "MOTO + TV" o "MOTO / TV"
        items = re.split(r'\s*[+/]\s*', art_raw)
        
        for item in items:
            item = item.strip()
            if not item or item in ["-", "NAN", "NONE"]: 
                continue
                
            # Unificar nombres (arregla errores de tipeo comunes)
            if item.startswith("VENTI"): 
                item = "VENTILADOR"
            elif "SOMIER" in item: 
                item = "SOMMIER"
                
            conteo[item] += 1

    # 🔥 Mostrar TODOS los artículos (le sacamos el límite de 10)
    resumen_ventas = conteo.most_common()
    total_articulos = sum(conteo.values())

    # 4. Traer movimientos de stock (Últimos 15)
    ultimos_movimientos = MovimientoStock.query.order_by(MovimientoStock.fecha.desc()).limit(15).all()

    # 5. Calcular ingresos del mes actual
    hoy = datetime.now()
    pagos_mes = Pago.query.filter(
        db.extract('month', Pago.fecha) == hoy.month,
        db.extract('year', Pago.fecha) == hoy.year
    ).all()
    ingresos_mes = sum(p.monto for p in pagos_mes)

    return render_template(
        'resumen.html',
        resumen_ventas=resumen_ventas,
        meses_dict=meses_dict,
        mes_filtro=mes_filtro,
        total_articulos=total_articulos,
        movimientos=ultimos_movimientos,
        ingresos_mes=ingresos_mes
    )