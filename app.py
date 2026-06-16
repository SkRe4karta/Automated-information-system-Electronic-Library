import os
from datetime import datetime
from flask import Flask
from markupsafe import Markup
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
import markdown
from sqlalchemy.engine import Engine
from sqlalchemy import event

from config import Config
from models import db, Role, User, Genre, Book, Cover, Review, ReviewStatus
from auth import auth_bp
from books import books_bp
from variants import variants_bp

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Для выполнения данного действия необходимо пройти процедуру аутентификации"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(variants_bp)

    # Register custom context processors / filters
    @app.context_processor
    def inject_datetime():
        from flask import request
        def query_params_without_page():
            params = {}
            for key in request.args.keys():
                if key == 'page':
                    continue
                values = request.args.getlist(key)
                if len(values) > 1:
                    params[key] = values
                elif len(values) == 1:
                    params[key] = values[0]
            return params
        return {
            'datetime': datetime,
            'query_params_without_page': query_params_without_page
        }

    @app.template_filter('markdown')
    def markdown_filter(text):
        if not text:
            return ""
        import bleach
        # 1. Render markdown to HTML
        html = markdown.markdown(text)
        # 2. Clean HTML with bleach
        allowed_tags = [
            'p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 
            'blockquote', 'code', 'pre', 'h1', 'h2', 'h3', 'h4', 'a'
        ]
        allowed_attrs = {
            'a': ['href', 'title', 'target']
        }
        allowed_protocols = ['http', 'https', 'mailto']
        safe_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, protocols=allowed_protocols)
        # 3. Return as Markup
        return Markup(safe_html)

    # Seed Database function
    with app.app_context():
        db.create_all()
        seed_database()

    return app

def seed_database():
    # 1. Seed Roles
    roles_data = [
        ('administrator', 'Администратор'),
        ('moderator', 'Модератор'),
        ('user', 'Пользователь')
    ]
    for r_name, r_desc in roles_data:
        if not Role.query.filter_by(name=r_name).first():
            role = Role(name=r_name, description=r_desc)
            db.session.add(role)
    db.session.commit()

    # 2. Seed Review Statuses
    statuses = ['pending', 'approved', 'rejected']
    for status_name in statuses:
        if not ReviewStatus.query.filter_by(name=status_name).first():
            status = ReviewStatus(name=status_name)
            db.session.add(status)
    db.session.commit()

    # 3. Seed Genres
    genres_list = [
        'Роман', 'Фантастика', 'Детектив', 'Научная литература', 
        'Поэзия', 'Биография', 'Исторический роман'
    ]
    genres_dict = {}
    for g_name in genres_list:
        genre = Genre.query.filter_by(name=g_name).first()
        if not genre:
            genre = Genre(name=g_name)
            db.session.add(genre)
            db.session.commit()
        genres_dict[g_name] = genre

    # 4. Seed Users
    admin_role = Role.query.filter_by(name='administrator').first()
    mod_role = Role.query.filter_by(name='moderator').first()
    user_role = Role.query.filter_by(name='user').first()

    users_data = [
        ('admin', 'admin', 'Администраторов', 'Админ', 'Админыч', admin_role.id),
        ('moderator', 'moderator', 'Модераторов', 'Модератор', 'Модерович', mod_role.id),
        ('user', 'user', 'Пользователев', 'Пользователь', 'Пользователевич', user_role.id)
    ]
    for login_val, password_val, l_name, f_name, m_name, r_id in users_data:
        if not User.query.filter_by(login=login_val).first():
            user = User(
                login=login_val,
                password_hash=generate_password_hash(password_val),
                last_name=l_name,
                first_name=f_name,
                middle_name=m_name,
                role_id=r_id
            )
            db.session.add(user)
    db.session.commit()

    # 5. Seed Books with Covers and Reviews
    if not Book.query.first():
        import hashlib
        
        upload_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'uploads', 'covers')
        os.makedirs(upload_folder, exist_ok=True)
        
        def add_cover_for_book(filename_seed, fallback_prefix, book_id):
            file_path = os.path.join(upload_folder, filename_seed)
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    file_data = f.read()
                md5_hash = hashlib.md5(file_data).hexdigest()
                cover = Cover(filename=filename_seed, mime_type="image/png", md5_hash=md5_hash, book_id=book_id)
                db.session.add(cover)
            else:
                png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
                md5_hash = hashlib.md5(png_data).hexdigest()
                filename = f"{fallback_prefix}_{md5_hash}.png"
                dest_path = os.path.join(upload_folder, filename)
                if not os.path.exists(dest_path):
                    with open(dest_path, 'wb') as f:
                        f.write(png_data)
                cover = Cover(filename=filename, mime_type="image/png", md5_hash=md5_hash, book_id=book_id)
                db.session.add(cover)

        # Seed Book 1
        book1 = Book(
            title="Мастер и Маргарита",
            description="Полноформатный шедевр русской литературы XX века. Роман совмещает элементы сатиры, мистики, любовной драмы и философской притчи.",
            year=1967,
            publisher="Художественная литература",
            author="Михаил Булгаков",
            pages=500
        )
        book1.genres.append(genres_dict['Роман'])
        book1.genres.append(genres_dict['Фантастика'])
        db.session.add(book1)
        db.session.flush()
        add_cover_for_book("master_margarita.png", "master_margarita", book1.id)

        # Seed Book 2
        book2 = Book(
            title="Приключения Шерлока Холмса",
            description="Сборник детективных рассказов Артура Конан Дойла о великом лондонском сыщике Шерлоке Холмсе и его верном помощнике докторе Ватсоне.",
            year=1892,
            publisher="George Newnes",
            author="Артур Конан Дойл",
            pages=320
        )
        book2.genres.append(genres_dict['Детектив'])
        db.session.add(book2)
        db.session.flush()
        add_cover_for_book("sherlock_holmes.png", "sherlock_holmes", book2.id)

        # Seed Book 3
        book3 = Book(
            title="Краткая история времени",
            description="Научно-популярная книга Стивена Хокинга, рассказывающая о космологии, черных дырах, пространстве-времени и квантовой механике простым языком.",
            year=1988,
            publisher="Bantam Books",
            author="Стивен Хокинг",
            pages=256
        )
        book3.genres.append(genres_dict['Научная литература'])
        db.session.add(book3)
        db.session.flush()
        add_cover_for_book("default_cover.png", "brief_history", book3.id)
        
        db.session.commit()

        # Seed reviews
        approved_status = ReviewStatus.query.filter_by(name='approved').first()
        pending_status = ReviewStatus.query.filter_by(name='pending').first()
        user_record = User.query.filter_by(login='user').first()
        mod_record = User.query.filter_by(login='moderator').first()

        if user_record and approved_status:
            review1 = Review(
                book_id=book1.id,
                user_id=user_record.id,
                rating=5,
                text="Потрясающий роман! Перечитывал несколько раз, каждый раз открываю для себя новые смыслы.",
                status_id=approved_status.id
            )
            db.session.add(review1)

        if mod_record and pending_status:
            review2 = Review(
                book_id=book2.id,
                user_id=mod_record.id,
                rating=4,
                text="Интересные классические детективы. Читается легко и с удовольствием.",
                status_id=pending_status.id
            )
            db.session.add(review2)

        db.session.commit()

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
