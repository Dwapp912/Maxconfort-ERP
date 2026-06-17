import os
from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, current_user, logout_user
from models import db, Usuario

# --- CONFIGURACIÓN PRINCIPAL ---
app = Flask(__name__)
# Se utiliza una clave genérica para el entorno de desarrollo público
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clave_secreta_desarrollo_123')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURACIÓN DE BASE DE DATOS ---
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # MODO NUBE (PostgreSQL)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print("✅ MODO NUBE: Conectado a PostgreSQL")

else:
    # MODO LOCAL (SQLite)
    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')

    if not os.path.exists(instance_path):
        os.makedirs(instance_path)

    db_path = os.path.join(instance_path, 'sistema_integral.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f"✅ MODO LOCAL: Conectado a Base de Datos de Desarrollo")

# Inicialización de DB
db.init_app(app)

# --- SISTEMA DE LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_route'
login_manager.login_message = None 

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# --- INICIALIZACIÓN DEL SISTEMA ---
with app.app_context():
    db.create_all()
    
    # Creación de usuario administrador de prueba para el entorno público
    if not Usuario.query.filter_by(username='admin').first():
        db.session.add(Usuario(username='admin', password='admin_password_123'))
        db.session.commit()
        print("✅ Usuario administrador de prueba creado.")

# --- BLUEPRINTS (MÓDULOS) ---
from routes.clientes import clientes_bp
from routes.stock import stock_bp 

app.register_blueprint(clientes_bp)
app.register_blueprint(stock_bp)

# --- RUTAS GENERALES ---
@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login_route'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Datos incorrectos")
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login_route'))

if __name__ == '__main__':
    app.run(debug=True)import os
from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, current_user, logout_user
from models import db, Usuario

# --- CONFIGURACIÓN PRINCIPAL ---
app = Flask(__name__)
# Se utiliza una clave genérica para el entorno de desarrollo público
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clave_secreta_desarrollo_123')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CONFIGURACIÓN DE BASE DE DATOS ---
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # MODO NUBE (PostgreSQL)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print("✅ MODO NUBE: Conectado a PostgreSQL")

else:
    # MODO LOCAL (SQLite)
    basedir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.join(basedir, 'instance')

    if not os.path.exists(instance_path):
        os.makedirs(instance_path)

    db_path = os.path.join(instance_path, 'sistema_integral.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    print(f"✅ MODO LOCAL: Conectado a Base de Datos de Desarrollo")

# Inicialización de DB
db.init_app(app)

# --- SISTEMA DE LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_route'
login_manager.login_message = None 

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# --- INICIALIZACIÓN DEL SISTEMA ---
with app.app_context():
    db.create_all()
    
    # Creación de usuario administrador de prueba para el entorno público
    if not Usuario.query.filter_by(username='admin').first():
        db.session.add(Usuario(username='admin', password='admin_password_123'))
        db.session.commit()
        print("✅ Usuario administrador de prueba creado.")

# --- BLUEPRINTS (MÓDULOS) ---
from routes.clientes import clientes_bp
from routes.stock import stock_bp 

app.register_blueprint(clientes_bp)
app.register_blueprint(stock_bp)

# --- RUTAS GENERALES ---
@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login_route'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Datos incorrectos")
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login_route'))

if __name__ == '__main__':
    app.run(debug=True)