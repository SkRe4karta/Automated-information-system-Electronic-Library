from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from functools import wraps
from models import User

auth_bp = Blueprint('auth', __name__)

def check_role(allowed_roles):
    """
    Decorator to check if the current user has one of the allowed roles.
    If not authenticated, redirects to login page.
    If authenticated but role not allowed, redirects to index page.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Для выполнения данного действия необходимо пройти процедуру аутентификации", "warning")
                return redirect(url_for('auth.login'))
            if current_user.role.name not in allowed_roles:
                flash("У вас недостаточно прав для выполнения данного действия", "danger")
                return redirect(url_for('books.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('books.index'))
        
    if request.method == 'POST':
        login_val = request.form.get('login')
        password_val = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(login=login_val).first()
        
        if not user or not check_password_hash(user.password_hash, password_val):
            flash("Невозможно аутентифицироваться с указанными логином и паролем", "danger")
            return render_template('login.html')
            
        login_user(user, remember=remember)
        
        # Redirect to next page if available
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('books.index'))
        
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    logout_user()
    referrer = request.referrer
    # Avoid redirecting back to secure routes which will immediately redirect to login
    if referrer and ('/create' not in referrer) and ('/edit' not in referrer) and ('/delete' not in referrer) and ('/reviews/create' not in referrer) and ('/my-' not in referrer) and ('/moderation' not in referrer):
        return redirect(referrer)
    return redirect(url_for('books.index'))
