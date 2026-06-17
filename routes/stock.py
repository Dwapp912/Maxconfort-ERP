import os
import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required
from werkzeug.utils import secure_filename
from models import db, Producto, MovimientoStock
from datetime import datetime

# --- IMPORTACIONES PARA CLOUDINARY ---
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- CONFIGURACIÓN DE CLOUDINARY ---
cloudinary.config(
  cloud_name = "drfmvs6sz",
  api_key = "882627359358269",
  api_secret = "H247Img5NcYLqSYrQ0CNr_UWUJg"
)

stock_bp = Blueprint('stock', __name__)

# --- RUTA PRINCIPAL ---
@stock_bp.route('/stock')
@login_required
def stock():
    edit_id = request.args.get('edit')
    prod_a_editar = Producto.query.get(edit_id) if edit_id else None
    productos = Producto.query.all()
    return render_template('stock.html', productos=productos, edit_prod=prod_a_editar)

# --- AGREGAR / EDITAR (CON CLOUDINARY) ---
@stock_bp.route('/stock/agregar', methods=['POST'])
@login_required
def agregar_producto():
    p_id = request.form.get('id')
    
    # Manejo de la Imagen
    imagen = request.files.get('imagen')
    url_imagen = request.form.get('url_actual', '')

    # --- LÓGICA DE SUBIDA A CLOUDINARY ---
    if imagen and imagen.filename != '':
        try:
            # Subimos la imagen a Cloudinary
            upload_result = cloudinary.uploader.upload(imagen)
            # Extraemos la URL segura (https)
            url_imagen = upload_result.get('secure_url')
            flash("✅ Imagen subida a la nube correctamente.")
        except Exception as e:
            flash(f"⚠️ Error al subir la imagen: {str(e)}")
            # Si falla la subida, se mantiene la url_actual (o vacío si era nuevo)
    
    datos = {
        'codigo': request.form.get('codigo'),
        'nombre': request.form.get('nombre'),
        'marca': request.form.get('marca'),
        'categoria': request.form.get('categoria'),
        'cantidad': int(request.form.get('cantidad') or 0),
        'imagen_url': url_imagen
    }

    try:
        if p_id: 
            Producto.query.filter_by(id=p_id).update(datos)
            flash("✅ Producto actualizado.")
        else: 
            # Verificar duplicados
            if Producto.query.filter_by(codigo=datos['codigo']).first():
                flash("⚠️ El código ya existe.")
                return redirect(url_for('stock.stock'))
            
            db.session.add(Producto(**datos))
            flash("✅ Producto creado.")
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error: {e}")

    return redirect(url_for('stock.stock'))

# --- BORRAR ---
@stock_bp.route('/stock/borrar/<int:id>')
@login_required
def borrar_producto(id):
    p = Producto.query.get(id)
    if p:
        db.session.delete(p)
        db.session.commit()
        flash("🗑️ Producto eliminado.")
    return redirect(url_for('stock.stock'))

# --- HISTORIAL (VISTA) ---
@stock_bp.route('/stock/historial')
@login_required
def ver_historial():
    movimientos = MovimientoStock.query.order_by(MovimientoStock.fecha.desc()).all()
    productos = Producto.query.all()
    return render_template('historial_stock.html', movimientos=movimientos, productos_lista=productos)

# --- CARGAR ENTRADA MANUAL (PROVEEDORES) ---
@stock_bp.route('/stock/historial/entrada', methods=['POST'])
@login_required
def cargar_entrada_historial():
    try:
        p_id = request.form.get('producto_id')
        cantidad = int(request.form.get('cantidad') or 0)
        
        # Validación de fecha segura
        fecha_str = request.form.get('fecha')
        if fecha_str:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d')
        else:
            fecha = datetime.now()
        
        prod = Producto.query.get(p_id)
        if prod:
            prod.cantidad += cantidad
            
            mov = MovimientoStock(
                producto_id=p_id, 
                tipo='ENTRADA', 
                cantidad=cantidad, 
                fecha=fecha, 
                detalle=f"Ingreso Manual: {prod.nombre}"
            )
            db.session.add(mov)
            db.session.commit()
            flash("✅ Entrada registrada correctamente.")
        else:
            flash("⚠️ Producto no encontrado.")

    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al cargar entrada: {e}")
        
    return redirect(url_for('stock.ver_historial'))

@stock_bp.route('/stock/historial/borrar/<int:id>')
@login_required
def borrar_movimiento(id):
    mov = MovimientoStock.query.get(id)
    if mov:
        db.session.delete(mov)
        db.session.commit()
    return redirect(url_for('stock.ver_historial'))

# --- EXPORTAR ---
@stock_bp.route('/stock/exportar')
@login_required
def exportar_stock():
    try:
        productos = Producto.query.all()
        data = []
        for p in productos:
            data.append({
                'CODIGO': p.codigo,
                'NOMBRE': p.nombre,
                'MARCA': p.marca,
                'CATEGORIA': p.categoria,
                'CANTIDAD': p.cantidad,
                'IMAGEN': p.imagen_url
            })
        
        df = pd.DataFrame(data)
        filename = "Stock_Actual.xlsx"
        df.to_excel(filename, index=False)
        return send_file(filename, as_attachment=True)
    except Exception as e:
        flash(f"❌ Error al exportar: {e}")
        return redirect(url_for('stock.stock'))

# --- IMPORTAR ---
@stock_bp.route('/stock/importar', methods=['POST'])
@login_required
def importar_stock():
    file = request.files.get('file')
    if not file:
        return redirect(url_for('stock.stock'))

    try:
        filename = file.filename.lower()
        if filename.endswith('.csv'):
            df = pd.read_csv(file, sep=';', encoding='latin-1')
            if len(df.columns) < 2:
                file.seek(0)
                df = pd.read_csv(file, sep=',', encoding='utf-8')
        else:
            df = pd.read_excel(file)

        df = df.fillna('')
        nuevos = 0
        actualizados = 0

        for _, row in df.iterrows():
            codigo = str(row.get('CODIGO', '')).strip().replace('.0', '')
            if not codigo: continue

            prod = Producto.query.filter_by(codigo=codigo).first()
            
            datos = {
                'nombre': str(row.get('NOMBRE', '')).strip(),
                'marca': str(row.get('MARCA', '')).strip(),
                'categoria': str(row.get('CATEGORIA', '')).strip(),
                'cantidad': int(row.get('CANTIDAD', 0) or 0)
            }

            if prod:
                prod.cantidad = datos['cantidad']
                actualizados += 1
            else:
                nuevo = Producto(codigo=codigo, **datos)
                db.session.add(nuevo)
                nuevos += 1

        db.session.commit()
        flash(f"✅ Importación: {nuevos} nuevos, {actualizados} actualizados.")

    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al importar: {e}")

    return redirect(url_for('stock.stock'))

# --- AJUSTE RÁPIDO DE STOCK (+ / -) SIN RECARGA ---
@stock_bp.route('/stock/ajuste_rapido/<int:id>/<accion>', methods=['POST'])
@login_required
def ajuste_rapido(id, accion):
    producto = Producto.query.get_or_404(id)
    
    if accion == 'sumar':
        producto.cantidad += 1
        mov = MovimientoStock(
            producto_id=producto.id,
            tipo="ENTRADA",
            cantidad=1,
            fecha=datetime.now(),
            detalle="Ajuste manual (+1)"
        )
        db.session.add(mov)

    elif accion == 'restar':
        if producto.cantidad > 0:
            producto.cantidad -= 1
            mov = MovimientoStock(
                producto_id=producto.id,
                tipo="SALIDA",
                cantidad=1,
                fecha=datetime.now(),
                detalle="Ajuste manual (-1)"
            )
            db.session.add(mov)
        else:
            return jsonify({
                'success': False,
                'error': 'El stock ya está en 0',
                'cantidad': producto.cantidad
            })

    db.session.commit()
    
    return jsonify({
        'success': True,
        'cantidad': producto.cantidad
    })