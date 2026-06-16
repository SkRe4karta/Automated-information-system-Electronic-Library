import os
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from models import db, Book, Genre, Cover, Review, ReviewStatus
from auth import check_role
import bleach

books_bp = Blueprint('books', __name__)

def get_md5_hash(file_data):
    md5 = hashlib.md5()
    md5.update(file_data)
    return md5.hexdigest()

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@books_bp.route('/')
@books_bp.route('/books')
def index():
    query = Book.query.order_by(Book.year.desc())

    # Pagination: 10 books per page
    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        'index.html',
        books=pagination.items,
        pagination=pagination
    )

@books_bp.route('/books/<int:book_id>')
def view(book_id):
    book = Book.query.get_or_404(book_id)

    # Variant 1: on the book page only approved reviews are shown.
    reviews = (
        Review.query
        .filter_by(book_id=book.id)
        .join(ReviewStatus)
        .filter(ReviewStatus.name == 'approved')
        .order_by(Review.created_at.desc())
        .all()
    )

    user_review = None
    if current_user.is_authenticated:
        user_review = Review.query.filter_by(book_id=book.id, user_id=current_user.id).first()

    return render_template(
        'books/view.html',
        book=book,
        reviews=reviews,
        user_review=user_review
    )

@books_bp.route('/books/create', methods=['GET', 'POST'])
@check_role(['administrator'])
def create():
    genres = Genre.query.all()
    if request.method == 'POST':
        saved_file_path = None
        try:
            title = request.form.get('title')
            description = request.form.get('description')
            year = int(request.form.get('year'))
            publisher = request.form.get('publisher')
            author = request.form.get('author')
            pages = int(request.form.get('pages'))
            genre_ids = request.form.getlist('genres')
            
            if not title or title.strip() == '':
                flash("Название книги не может быть пустым.", "danger")
                return render_template('books/form.html', genres=genres, action='create', form_data=request.form)
            if not description or description.strip() == '':
                flash("Описание книги не может быть пустым.", "danger")
                return render_template('books/form.html', genres=genres, action='create', form_data=request.form)
            
            # Check cover file upload (required on creation)
            cover_file = request.files.get('cover')
            if not cover_file or cover_file.filename == '':
                flash("Обложка книги обязательна к загрузке.", "danger")
                return render_template('books/form.html', genres=genres, action='create', form_data=request.form)

            if not allowed_file(cover_file.filename):
                flash("Неразрешенный формат файла обложки.", "danger")
                return render_template('books/form.html', genres=genres, action='create', form_data=request.form)

            # Read file data to get MD5 hash
            file_data = cover_file.read()
            md5_hash = get_md5_hash(file_data)
            mime_type = cover_file.content_type
            orig_filename = secure_filename(cover_file.filename)
            
            # Check if cover with the same md5 hash already exists
            existing_cover = Cover.query.filter_by(md5_hash=md5_hash).first()
            
            if existing_cover:
                # Use the existing filename, do not save duplicate physical file
                filename = existing_cover.filename
            else:
                # Save new file with unique name (UUID + extension)
                ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'jpg'
                filename = f"{uuid.uuid4().hex}.{ext}"
                
                # Make sure directories exist
                os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                with open(file_path, 'wb') as f:
                    f.write(file_data)
                saved_file_path = file_path

            # Clean description before saving
            cleaned_description = bleach.clean(description)

            # Create Book
            new_book = Book(
                title=title,
                description=cleaned_description,
                year=year,
                publisher=publisher,
                author=author,
                pages=pages
            )
            
            # Assign Genres
            for g_id in genre_ids:
                genre = Genre.query.get(int(g_id))
                if genre:
                    new_book.genres.append(genre)

            db.session.add(new_book)
            db.session.flush() # Flush to get new_book.id

            # Create Cover
            cover = Cover(
                filename=filename,
                mime_type=mime_type,
                md5_hash=md5_hash,
                book_id=new_book.id
            )
            db.session.add(cover)
            db.session.commit()

            flash("Книга успешно добавлена!", "success")
            return redirect(url_for('books.view', book_id=new_book.id))

        except Exception as e:
            db.session.rollback()
            if saved_file_path and os.path.exists(saved_file_path):
                try:
                    os.remove(saved_file_path)
                except Exception as cleanup_err:
                    current_app.logger.error(f"Failed to delete uploaded file after DB error: {str(cleanup_err)}")
            current_app.logger.error(f"Error saving book: {str(e)}")
            flash("При сохранении данных возникла ошибка. Проверьте корректность введённых данных.", "danger")
            return render_template('books/form.html', genres=genres, action='create', form_data=request.form)

    return render_template('books/form.html', genres=genres, action='create', form_data={})

@books_bp.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@check_role(['administrator', 'moderator'])
def edit(book_id):
    book = Book.query.get_or_404(book_id)
    genres = Genre.query.all()
    
    if request.method == 'POST':
        try:
            book.title = request.form.get('title')
            description = request.form.get('description')
            book.year = int(request.form.get('year'))
            book.publisher = request.form.get('publisher')
            book.author = request.form.get('author')
            book.pages = int(request.form.get('pages'))
            genre_ids = request.form.getlist('genres')

            if not book.title or book.title.strip() == '':
                flash("Название книги не может быть пустым.", "danger")
                return render_template('books/form.html', book=book, genres=genres, action='edit', form_data=request.form)
            if not description or description.strip() == '':
                flash("Описание книги не может быть пустым.", "danger")
                return render_template('books/form.html', book=book, genres=genres, action='edit', form_data=request.form)

            # Clean description before saving
            book.description = bleach.clean(description)

            # Update Genres
            book.genres = []
            for g_id in genre_ids:
                genre = Genre.query.get(int(g_id))
                if genre:
                    book.genres.append(genre)

            db.session.commit()
            flash("Книга успешно отредактирована!", "success")
            return redirect(url_for('books.view', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing book: {str(e)}")
            flash("При сохранении данных возникла ошибка. Проверьте корректность введённых данных.", "danger")
            return render_template('books/form.html', book=book, genres=genres, action='edit', form_data=request.form)

    # Prepopulate genres IDs for the view
    form_data = {
        'title': book.title,
        'description': book.description,
        'year': book.year,
        'publisher': book.publisher,
        'author': book.author,
        'pages': book.pages,
        'genres': [g.id for g in book.genres]
    }
    return render_template('books/form.html', book=book, genres=genres, action='edit', form_data=form_data)

@books_bp.route('/books/<int:book_id>/delete', methods=['POST'])
@check_role(['administrator'])
def delete(book_id):
    book = Book.query.get_or_404(book_id)
    title = book.title
    try:
        # Check if the cover needs to be physically deleted from disk
        if book.cover:
            filename = book.cover.filename
            
            # Find if there are OTHER covers using this filename
            other_covers_count = Cover.query.filter(Cover.filename == filename, Cover.book_id != book.id).count()
            
            # Delete database book record (will cascade delete BookGenre, Review, Cover records)
            db.session.delete(book)
            db.session.commit()
            
            # If no other books reference this file, remove it
            if other_covers_count == 0:
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
        else:
            db.session.delete(book)
            db.session.commit()
            
        flash(f"Книга «{title}» успешно удалена.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting book: {str(e)}")
        flash("При удалении книги возникла ошибка.", "danger")
        
    return redirect(url_for('books.index'))

@books_bp.route('/books/<int:book_id>/reviews/create', methods=['GET', 'POST'])
@login_required
def create_review(book_id):
    book = Book.query.get_or_404(book_id)
    
    # Check if user has already written a review
    existing_review = Review.query.filter_by(book_id=book.id, user_id=current_user.id).first()
    if existing_review:
        flash("Вы уже оставили рецензию на эту книгу.", "warning")
        return redirect(url_for('books.view', book_id=book.id))
        
    if request.method == 'POST':
        try:
            rating_val = request.form.get('rating')
            try:
                rating = int(rating_val)
            except (ValueError, TypeError):
                flash("Некорректное значение оценки.", "danger")
                return render_template('books/review.html', book=book, form_data=request.form)
                
            if rating < 0 or rating > 5:
                flash("Оценка должна быть в диапазоне от 0 до 5.", "danger")
                return render_template('books/review.html', book=book, form_data=request.form)

            text = request.form.get('text')
            
            if not text or text.strip() == '':
                flash("Текст рецензии не может быть пустым.", "danger")
                return render_template('books/review.html', book=book, form_data=request.form)
            
            # Clean text before saving
            cleaned_text = bleach.clean(text)

            # Create review
            new_review = Review(
                book_id=book.id,
                user_id=current_user.id,
                rating=rating,
                text=cleaned_text
            )
            
            pending_status = ReviewStatus.query.filter_by(name='pending').first()
            if pending_status:
                new_review.status_id = pending_status.id

            db.session.add(new_review)
            db.session.commit()
            
            flash("Рецензия успешно отправлена на модерацию.", "success")

            return redirect(url_for('books.view', book_id=book.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding review: {str(e)}")
            flash("При сохранении рецензии возникла ошибка. Проверьте корректность данных.", "danger")
            return render_template('books/review.html', book=book, form_data=request.form)
            
    return render_template('books/review.html', book=book, form_data={})
