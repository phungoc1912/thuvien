# -*- coding: utf-8 -*-
import os
import subprocess
import shutil
import urllib.parse
import requests
import sqlite3
import json
import zipfile
import tempfile
import unicodedata
import re
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session, Response, jsonify
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import or_, case, and_, event, func, not_
from sqlalchemy.engine import Engine
from xml.etree import ElementTree as ET
from functools import wraps
from PIL import Image # Them thu vien Pillow de xu ly anh

# --- CAU HINH UNG DUNG ---
CONFIG_FILE = 'config.json'

def load_config():
    """Tai cau hinh tu file config.json, hoac tao file neu chua co."""
    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kavita_library_data')
    default_config = {
        'library_name': 'Thư Viện Sách',
        'data_path': default_path,
        'port': 5000,
        'theme': 'dark',
        'theme_color': 'cyan'
    }
    if not os.path.exists(CONFIG_FILE):
        save_config(default_config)
        return default_config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Dam bao tat ca cac key deu ton tai
            for key, value in default_config.items():
                config.setdefault(key, value)
            return config
    except (json.JSONDecodeError, IOError):
        save_config(default_config)
        return default_config

def save_config(config):
    """Luu cau hinh vao file config.json."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Tai cau hinh va thiet lap cac duong dan chinh
config = load_config()
DATA_ROOT = os.path.abspath(config.get('data_path'))
SAFE_BROWSING_ROOT = os.path.expanduser('~') # Gioi han trinh duyet file trong thu muc home

UPLOAD_FOLDER = os.path.join(DATA_ROOT, 'books')
COVER_FOLDER = os.path.join(DATA_ROOT, 'static/covers')
DATABASE_FILE = os.path.join(DATA_ROOT, 'books.db')

# Cac hang so khac
ALLOWED_EXTENSIONS = {'epub', 'mobi', 'pdf', 'azw3', 'txt', 'azw', 'doc', 'docx', 'rtf', 'html', 'lit', 'prc', 'oeb'}
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'password'
GUEST_USERNAME = 'guest'
BOOKS_PER_PAGE = 18
COVER_MAX_HEIGHT = 600

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COVER_FOLDER'] = COVER_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_FILE}'
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['DATA_ROOT'] = DATA_ROOT

db = SQLAlchemy(app)

# --- CAC HAM TIEN ICH VA KHOI TAO ---

def remove_diacritics(text):
    if not isinstance(text, str):
        return text
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)
    text = text.replace('đ', 'd')
    return text

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    dbapi_connection.create_function("unaccent", 1, remove_diacritics)

# --- MODELS CO SO DU LIEU ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

book_list_association = db.Table('book_list_association',
    db.Column('book_id', db.Integer, db.ForeignKey('book.id'), primary_key=True),
    db.Column('book_list_id', db.Integer, db.ForeignKey('book_list.id'), primary_key=True)
)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    title = db.Column(db.String(200), nullable=False, index=True)
    author = db.Column(db.String(200), index=True)
    format = db.Column(db.String(20))
    tags = db.Column(db.String(500))
    description = db.Column(db.Text)
    rating = db.Column(db.Integer, default=0)
    series = db.Column(db.String(200))
    series_index = db.Column(db.Integer, default=1)
    publisher = db.Column(db.String(200))
    pubdate = db.Column(db.String(100))
    language = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('books', lazy=True, cascade="all, delete-orphan"))
    has_cover = db.Column(db.Boolean, default=False, nullable=False)

class BookList(db.Model):
    __tablename__ = 'book_list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('book_lists', lazy='dynamic', cascade="all, delete-orphan"))
    books = db.relationship('Book', secondary=book_list_association, lazy='dynamic',
                            backref=db.backref('lists', lazy='dynamic'))

class ReadingHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    last_read = db.Column(db.DateTime, default=datetime.utcnow)
    settings = db.Column(db.Text, nullable=True)

class BookMark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)

class GuestPermission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    can_rate = db.Column(db.Boolean, default=False, nullable=False)
    can_edit_books = db.Column(db.Boolean, default=False, nullable=False)
    can_upload_books = db.Column(db.Boolean, default=False, nullable=False)
    can_delete_books = db.Column(db.Boolean, default=False, nullable=False)
    can_convert_books = db.Column(db.Boolean, default=False, nullable=False)
    can_bookmark = db.Column(db.Boolean, default=False, nullable=False)
    can_favorite = db.Column(db.Boolean, default=False, nullable=False) # Them quyen yeu thich

def get_cover_path(book):
    """Tao duong dan file anh bia tinh cho mot cuon sach."""
    user_cover_dir = os.path.join(app.config['COVER_FOLDER'], str(book.user_id))
    return os.path.join(user_cover_dir, f"{book.id}.jpg")

def generate_and_save_cover(book):
    """
    Trich xuat, nen va luu anh bia cho mot cuon sach.
    Tra ve True neu thanh cong, False neu that bai.
    """
    if not book or not book.id:
        return False

    user_book_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(book.user_id))
    book_filepath = os.path.join(user_book_folder, book.filename)
    if not os.path.exists(book_filepath):
        return False

    final_cover_path = get_cover_path(book)
    os.makedirs(os.path.dirname(final_cover_path), exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_cover:
        temp_cover_path = tmp_cover.name

    try:
        subprocess.run(
            ["ebook-meta", book_filepath, "--get-cover", temp_cover_path],
            check=True, capture_output=True, timeout=30
        )

        if os.path.exists(temp_cover_path) and os.path.getsize(temp_cover_path) > 0:
            with Image.open(temp_cover_path) as img:
                if img.height > COVER_MAX_HEIGHT:
                    ratio = COVER_MAX_HEIGHT / img.height
                    new_width = int(img.width * ratio)
                    img = img.resize((new_width, COVER_MAX_HEIGHT), Image.Resampling.LANCZOS)
                
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                    
                img.save(final_cover_path, 'jpeg', quality=80, optimize=True)
            
            book.has_cover = True
            db.session.commit()
            return True
        else:
            book.has_cover = False
            db.session.commit()
            return False

    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        print(f"Loi khi tao anh bia cho book ID {book.id}: {e}")
        book.has_cover = False
        db.session.commit()
        return False
    finally:
        if os.path.exists(temp_cover_path):
            os.remove(temp_cover_path)

def initialize_database():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['COVER_FOLDER'], exist_ok=True)
    os.makedirs(app.static_folder, exist_ok=True)
    
    default_cover_path = os.path.join(app.static_folder, 'default_cover.jpg')
    if not os.path.exists(default_cover_path):
        try:
            # Using a neutral placeholder
            r = requests.get("https://placehold.co/400x600/e2e8f0/4a5568?text=No+Cover", stream=True)
            if r.status_code == 200:
                with open(default_cover_path, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
        except Exception as e:
            print(f"Khong the tai anh bia mac dinh: {e}")

    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username=ADMIN_USERNAME).first():
            db.session.add(User(username=ADMIN_USERNAME, password=ADMIN_PASSWORD, is_admin=True))
        if not User.query.filter_by(username=GUEST_USERNAME).first():
            db.session.add(User(username=GUEST_USERNAME, password="", is_admin=False))
        if not GuestPermission.query.first():
            db.session.add(GuestPermission())
        db.session.commit()

# --- DECORATORS & CONTEXT PROCESSORS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Bạn cần đăng nhập để xem trang này.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_book_permission(book_id):
    book = Book.query.get_or_404(book_id)
    if session.get('is_admin') or (book and book.user_id == session.get('user_id')):
        return book
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_global_vars():
    permissions = GuestPermission.query.first()
    user_lists = []
    library_users = {}
    
    if 'user_id' in session:
        user_id = session.get('user_id')
        user_lists = BookList.query.filter_by(user_id=user_id).order_by(BookList.name).all()

    if 'is_admin' in session and session['is_admin']:
        library_users = User.query.filter(User.username != ADMIN_USERNAME, User.username != GUEST_USERNAME).order_by(User.username).all()

    return dict(
        guest_permissions=permissions,
        user_book_lists=user_lists,
        library_users=library_users,
        GUEST_USERNAME=GUEST_USERNAME,
        ADMIN_USERNAME=ADMIN_USERNAME,
        # Pass config to templates for JS fallback
        app_config=load_config() 
    )

# -------------------- MAU HTML --------------------

LAYOUT_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ app_config.library_name }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="//unpkg.com/alpinejs" defer></script>
    <script>
        // Set theme based on localStorage or system preference
        (function() {
            const theme = localStorage.getItem('kavita_theme') || '{{ app_config.theme }}';
            if (theme === 'light') {
                document.documentElement.classList.remove('dark');
            } else {
                document.documentElement.classList.add('dark');
            }
        })();
        
        // Tailwind config for dark mode and theme colors
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        theme: {
                            '50': 'var(--theme-50)', '100': 'var(--theme-100)',
                            '200': 'var(--theme-200)', '300': 'var(--theme-300)',
                            '400': 'var(--theme-400)', '500': 'var(--theme-500)',
                            '600': 'var(--theme-600)', '700': 'var(--theme-700)',
                            '800': 'var(--theme-800)', '900': 'var(--theme-900)',
                            '950': 'var(--theme-950)',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        /* Define color palettes for different themes */
        .theme-cyan {
            --theme-50: #ecfeff; --theme-100: #cffafe; --theme-200: #a5f3fd;
            --theme-300: #67e8f9; --theme-400: #22d3ee; --theme-500: #06b6d4;
            --theme-600: #0891b2; --theme-700: #0e7490; --theme-800: #155e75;
            --theme-900: #164e63; --theme-950: #083344;
        }
        .theme-blue {
            --theme-50: #eff6ff; --theme-100: #dbeafe; --theme-200: #bfdbfe;
            --theme-300: #93c5fd; --theme-400: #60a5fa; --theme-500: #3b82f6;
            --theme-600: #2563eb; --theme-700: #1d4ed8; --theme-800: #1e40af;
            --theme-900: #1e3a8a; --theme-950: #172554;
        }
        .theme-emerald {
            --theme-50: #ecfdf5; --theme-100: #d1fae5; --theme-200: #a7f3d0;
            --theme-300: #6ee7b7; --theme-400: #34d399; --theme-500: #10b981;
            --theme-600: #059669; --theme-700: #047857; --theme-800: #065f46;
            --theme-900: #064e3b; --theme-950: #022c22;
        }
        .theme-rose {
            --theme-50: #fff1f2; --theme-100: #ffe4e6; --theme-200: #fecdd3;
            --theme-300: #fda4af; --theme-400: #fb7185; --theme-500: #f43f5e;
            --theme-600: #e11d48; --theme-700: #be123c; --theme-800: #9f1239;
            --theme-900: #881337; --theme-950: #4c0519;
        }
        .theme-indigo {
            --theme-50: #eef2ff; --theme-100: #e0e7ff; --theme-200: #c7d2fe;
            --theme-300: #a5b4fc; --theme-400: #818cf8; --theme-500: #6366f1;
            --theme-600: #4f46e5; --theme-700: #4338ca; --theme-800: #3730a3;
            --theme-900: #312e81; --theme-950: #1e1b4b;
        }
        .theme-violet {
            --theme-50: #f5f3ff; --theme-100: #ede9fe; --theme-200: #ddd6fe;
            --theme-300: #c4b5fd; --theme-400: #a78bfa; --theme-500: #8b5cf6;
            --theme-600: #7c3aed; --theme-700: #6d28d9; --theme-800: #5b21b6;
            --theme-900: #4c1d95; --theme-950: #2e1065;
        }
        .theme-fuchsia {
            --theme-50: #fdf4ff; --theme-100: #fae8ff; --theme-200: #f5d0fe;
            --theme-300: #f0abfc; --theme-400: #e879f9; --theme-500: #d946ef;
            --theme-600: #c026d3; --theme-700: #a21caf; --theme-800: #86198f;
            --theme-900: #701a75; --theme-950: #4a044e;
        }
        .theme-orange {
            --theme-50: #fff7ed; --theme-100: #ffedd5; --theme-200: #fed7aa;
            --theme-300: #fdba74; --theme-400: #fb923c; --theme-500: #f97316;
            --theme-600: #ea580c; --theme-700: #c2410c; --theme-800: #9a3412;
            --theme-900: #7c2d12; --theme-950: #431407;
        }

        /* Custom scrollbar for dark/light mode */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        html.dark ::-webkit-scrollbar-track { background: #1f2937; }
        html:not(.dark) ::-webkit-scrollbar-track { background: #e5e7eb; }
        html.dark ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 4px; }
        html:not(.dark) ::-webkit-scrollbar-thumb { background: #9ca3af; border-radius: 4px; }
        html.dark ::-webkit-scrollbar-thumb:hover { background: #6b7280; }
        html:not(.dark) ::-webkit-scrollbar-thumb:hover { background: #6b7280; }

        .book-cover {
            height: 240px; width: 100%; object-fit: cover; object-position: top;
            transition: transform 0.3s ease;
            background-color: #e2e8f0; /* Light mode placeholder */
        }
        .dark .book-cover { background-color: #374151; } /* Dark mode placeholder */
        @media (min-width: 640px) { .book-cover { height: 300px; } }
        .book-card:hover .book-cover { transform: scale(1.05); }
        .interactive-star:hover { color: #f59e0b; }
        [x-cloak] { display: none !important; }
    </style>
</head>
<body class="bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-200 font-sans transition-colors duration-300">
    <div x-data="{ sidebarOpen: false }" class="flex min-h-screen">
        <!-- Overlay for mobile -->
        <div x-show="sidebarOpen" @click="sidebarOpen = false" class="fixed inset-0 bg-black bg-opacity-50 z-20 md:hidden" x-cloak></div>

        <!-- Sidebar -->
        <aside 
            class="w-64 bg-white dark:bg-gray-800 p-4 flex flex-col fixed h-full z-30 transform transition-transform duration-300 ease-in-out md:translate-x-0"
            :class="{'translate-x-0': sidebarOpen, '-translate-x-full': !sidebarOpen}">
            
            <div class="flex items-center justify-between">
                <h1 class="text-2xl font-bold text-gray-900 dark:text-white flex items-center">
                    <i class="fas fa-book-open text-theme-500 mr-2"></i> {{ app_config.library_name }}
                </h1>
                <button @click="sidebarOpen = false" class="md:hidden text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white">
                    <i class="fas fa-times text-2xl"></i>
                </button>
            </div>
            
            <nav class="flex-grow mt-8">
                <ul class="text-gray-600 dark:text-gray-300">
                    <li class="mb-4"><a href="{{ url_for('index') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-home w-6 mr-2"></i> Trang chủ</a></li>
                    <li class="mb-4"><a href="{{ url_for('favorites') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-heart w-6 mr-2 text-red-500"></i> Sách Yêu Thích</a></li>
                    <li class="mb-4"><a href="{{ url_for('bookmarks') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-bookmark w-6 mr-2 text-theme-500"></i> Sách đã đánh dấu</a></li>
                    
                    <li class="mb-2" x-data="{ open: false }">
                        <button @click="open = !open" class="w-full flex justify-between items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg">
                            <span class="flex items-center"><i class="fas fa-list-check w-6 mr-2"></i> Kệ sách</span>
                            <i class="fas transition-transform" :class="{'fa-chevron-down': open, 'fa-chevron-right': !open}"></i>
                        </button>
                        <ul x-show="open" class="pl-6 mt-1 space-y-1" x-transition>
                            {% for list in user_book_lists %}
                            <li><a href="{{ url_for('view_list', list_id=list.id) }}" class="block p-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200/50 dark:hover:bg-gray-700/50 rounded-md">{{ list.name }}</a></li>
                            {% endfor %}
                            <li>
                                <button onclick="document.getElementById('create-list-modal').classList.remove('hidden')" class="w-full text-left p-1.5 text-sm text-theme-600 dark:text-theme-500 hover:text-theme-700 dark:hover:text-theme-400 font-semibold">
                                    <i class="fas fa-plus-circle mr-1"></i> Tạo kệ sách mới
                                </button>
                            </li>
                        </ul>
                    </li>

                    <li class="mb-2"><hr class="border-gray-200 dark:border-gray-600"></li>

                    {% if session.get('is_admin') and library_users %}
                    <li class="mt-2 mb-2 text-sm font-semibold text-gray-400 dark:text-gray-500 px-2 uppercase">Thư viện Users</li>
                    {% for user in library_users %}
                    <li class="mb-1">
                        <a href="{{ url_for('view_user_library', user_id=user.id) }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg text-sm">
                            <i class="fas fa-user-circle w-6 mr-2"></i> <span>{{ user.username }}</span>
                        </a>
                    </li>
                    {% endfor %}
                    <li class="mb-2"><hr class="border-gray-200 dark:border-gray-600"></li>
                    {% endif %}
                    
                    <li class="mt-4 mb-4"><a href="{{ url_for('index') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-book w-6 mr-2"></i> Tất cả sách</a></li>
                    {% if session.get('is_admin') %}
                    <li class="mt-4 mb-4"><a href="{{ url_for('manage_users') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-users-cog w-6 mr-2"></i> Quản lý User</a></li>
                    <li class="mb-4"><a href="{{ url_for('guest_permissions') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-user-shield w-6 mr-2"></i> Quyền tài khoản Khách</a></li>
                    <li class="mb-4"><a href="{{ url_for('settings') }}" class="flex items-center p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><i class="fas fa-cogs w-6 mr-2"></i> Cài đặt</a></li>
                    {% endif %}
                </ul>
            </nav>
            {% if session.get('logged_in') and session.get('username') != GUEST_USERNAME %}
            <div class="mt-auto">
                <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">Quản lý</h2>
                <form method="POST" action="/upload" enctype="multipart/form-data" class="mb-2">
                     <label class="block w-full text-center px-3 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700 transition-colors cursor-pointer">
                        <i class="fas fa-upload mr-2"></i> Tải lên sách
                        <input type="file" name="files[]" class="hidden" multiple onchange="this.form.submit()">
                    </label>
                </form>
                <a href="{{ url_for('import_calibre') }}" class="block w-full text-center px-3 py-2 mt-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    <i class="fas fa-database mr-2"></i> Nhập từ Calibre
                </a>
            </div>
            {% elif session.get('username') == GUEST_USERNAME and guest_permissions and guest_permissions.can_upload_books %}
             <div class="mt-auto">
                <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">Quản lý</h2>
                <form method="POST" action="/upload" enctype="multipart/form-data" class="mb-2">
                     <label class="block w-full text-center px-3 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700 transition-colors cursor-pointer">
                        <i class="fas fa-upload mr-2"></i> Tải lên sách
                        <input type="file" name="files[]" class="hidden" multiple onchange="this.form.submit()">
                    </label>
                </form>
                <a href="{{ url_for('import_calibre') }}" class="block w-full text-center px-3 py-2 mt-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                    <i class="fas fa-database mr-2"></i> Nhập từ Calibre
                </a>
            </div>
            {% endif %}
        </aside>

        <!-- Main Content -->
        <main class="flex-1 flex flex-col md:ml-64">
            <!-- Top Bar -->
            <header class="bg-white/50 dark:bg-gray-800/50 backdrop-blur-sm p-3 flex items-center justify-between sticky top-0 z-10 border-b border-gray-200 dark:border-gray-700">
                <!-- Hamburger Menu Button -->
                <button @click="sidebarOpen = true" class="md:hidden text-gray-800 dark:text-white text-2xl">
                    <i class="fas fa-bars"></i>
                </button>

                <form method="GET" action="/" class="flex-grow md:flex-grow-0 md:w-1/2 ml-4">
                    <div class="relative">
                        <span class="absolute inset-y-0 left-0 flex items-center pl-3"><i class="fas fa-search text-gray-400 dark:text-gray-500"></i></span>
                        <input type="text" name="q" class="w-full bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white rounded-full py-2 pl-10 pr-4 focus:outline-none focus:ring-2 focus:ring-theme-500" placeholder="Tìm kiếm sách, tác giả..." value="{{ query or '' }}">
                    </div>
                </form>
                <div class="flex items-center">
                    {% if session.get('logged_in') %}
                        <div class="relative" x-data="{ open: false }">
                            <button @click="open = !open" class="flex items-center text-gray-800 dark:text-white ml-4">
                                <span class="hidden sm:inline">Xin chào, </span><strong class="mx-1">{{ session.get('username') }}</strong>
                                <i class="fas fa-caret-down ml-1"></i>
                            </button>
                            <div x-show="open" @click.away="open = false" class="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-700 rounded-lg shadow-xl z-20" x-cloak>
                                {% if session.get('username') != GUEST_USERNAME %}
                                <a href="{{ url_for('change_password') }}" class="block px-4 py-2 text-gray-800 dark:text-white hover:bg-gray-100 dark:hover:bg-gray-600">Đổi mật khẩu</a>
                                {% endif %}
                                <a href="{{ url_for('logout') }}" class="block px-4 py-2 text-gray-800 dark:text-white hover:bg-gray-100 dark:hover:bg-gray-600">Đăng xuất</a>
                            </div>
                        </div>
                    {% else %}
                        <a href="{{ url_for('login') }}" class="ml-4 px-4 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700 transition-colors">Đăng nhập</a>
                    {% endif %}
                </div>
            </header>

            <!-- Page Content -->
            <div class="p-4 md:p-6 flex-grow">
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="p-4 rounded-lg mb-6 shadow-lg border-l-4
                        {% if category == 'danger' %} bg-red-500/10 border-red-500 text-red-800 dark:text-red-300
                        {% elif category == 'success' %} bg-green-500/10 border-green-500 text-green-800 dark:text-green-300
                        {% elif category == 'warning' %} bg-yellow-500/10 border-yellow-500 text-yellow-800 dark:text-yellow-300
                        {% else %} bg-theme-500/10 border-theme-500 text-theme-800 dark:text-theme-300 {% endif %}">
                        {{ message }}
                      </div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                
                {{ content|safe }}

            </div>
        </main>
    </div>

    <!-- Modal tao ke sach -->
    <div id="create-list-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center hidden z-50 p-4">
        <div class="bg-white dark:bg-gray-800 rounded-lg p-6 max-w-sm w-full">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xl font-bold text-gray-900 dark:text-white">Tạo kệ sách mới</h3>
                <button onclick="document.getElementById('create-list-modal').classList.add('hidden')" class="text-gray-400 hover:text-gray-800 dark:hover:text-white text-2xl">&times;</button>
            </div>
            <form id="create-list-form">
                <div class="mb-4">
                    <label for="new-list-name" class="block text-gray-600 dark:text-gray-400 mb-2">Tên kệ sách</label>
                    <input type="text" id="new-list-name" name="name" class="w-full bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-theme-500" required>
                </div>
                <button type="submit" class="w-full px-4 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700">Tạo mới</button>
            </form>
        </div>
    </div>

    <script>
    // Set theme color class on body
    (function() {
        const color = localStorage.getItem('kavita_theme_color') || '{{ app_config.theme_color }}';
        document.body.classList.add(`theme-${color}`);
    })();

    if (document.getElementById('create-list-form')) {
        document.getElementById('create-list-form').addEventListener('submit', function(e) {
            e.preventDefault();
            const listName = document.getElementById('new-list-name').value;
            fetch('{{ url_for("create_list") }}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: listName }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Lỗi: ' + data.message);
                }
            })
            .catch((error) => {
                console.error('Error:', error);
                alert('Đã có lỗi xảy ra.');
            });
        });
    }
    </script>
</body>
</html>
"""

INDEX_TEMPLATE = """
{% if random_books %}
<div class="mb-12">
    <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Khám phá ngẫu nhiên</h2>
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 md:gap-6">
        {% for book in random_books %}
            <div class="book-card relative bg-white dark:bg-gray-800 rounded-lg overflow-hidden shadow-lg hover:shadow-xl dark:hover:shadow-theme-800/20 transition-shadow duration-300 group">
                <a href="{{ url_for('book_detail', book_id=book.id) }}">
                    <img src="{{ url_for('cover', book_id=book.id) }}" 
                         loading="lazy" 
                         class="book-cover" 
                         alt="Bìa sách {{ book.title }}"
                         onerror="this.onerror=null; this.src='{{ url_for('static', filename='default_cover.jpg') }}';">
                </a>
                {% if book.is_favorited %}
                <div class="absolute top-2 left-2 text-red-500 text-xl pointer-events-none drop-shadow-lg">
                    <i class="fas fa-heart"></i>
                </div>
                {% endif %}
                {% if book.is_bookmarked %}
                <div class="absolute top-2 right-2 text-theme-500 text-xl pointer-events-none drop-shadow-lg">
                    <i class="fas fa-bookmark"></i>
                </div>
                {% endif %}
                <div class="p-3">
                    <a href="{{ url_for('book_detail', book_id=book.id) }}">
                        <h3 class="font-bold text-gray-800 dark:text-white truncate group-hover:text-theme-600 dark:group-hover:text-theme-400">{{ book.title }}</h3>
                    </a>
                    <p class="text-sm text-gray-500 dark:text-gray-400 truncate">{{ book.author }}</p>
                </div>
            </div>
        {% endfor %}
    </div>
</div>
<hr class="border-gray-200 dark:border-gray-700 my-8">
{% endif %}

<h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">{{ page_title or 'Thư viện' }}</h2>
<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 md:gap-6">
    {% for book in pagination.items %}
        <div class="book-card relative bg-white dark:bg-gray-800 rounded-lg overflow-hidden shadow-lg hover:shadow-xl dark:hover:shadow-theme-800/20 transition-shadow duration-300 group">
            <a href="{{ url_for('book_detail', book_id=book.id) }}">
                <img src="{{ url_for('cover', book_id=book.id) }}"
                     loading="lazy"
                     class="book-cover" 
                     alt="Bìa sách {{ book.title }}"
                     onerror="this.onerror=null; this.src='{{ url_for('static', filename='default_cover.jpg') }}';">
            </a>
            {% if book.is_favorited %}
            <div class="absolute top-2 left-2 text-red-500 text-xl pointer-events-none drop-shadow-lg">
                <i class="fas fa-heart"></i>
            </div>
            {% endif %}
            {% if book.is_bookmarked %}
            <div class="absolute top-2 right-2 text-theme-500 text-xl pointer-events-none drop-shadow-lg">
                <i class="fas fa-bookmark"></i>
            </div>
            {% endif %}
            <div class="p-3">
                <a href="{{ url_for('book_detail', book_id=book.id) }}">
                    <h3 class="font-bold text-gray-800 dark:text-white truncate group-hover:text-theme-600 dark:group-hover:text-theme-400">{{ book.title }}</h3>
                </a>
                <p class="text-sm text-gray-500 dark:text-gray-400 truncate">{{ book.author }}</p>
                {% if is_admin %}
                <p class="text-xs text-gray-400 dark:text-gray-500 truncate mt-1"><i class="fas fa-user mr-1"></i>{{ book.owner_username }}</p>
                {% endif %}
            </div>
        </div>
    {% else %}
        <div class="col-span-full text-center py-12">
            <p class="text-gray-500 dark:text-gray-400">Không tìm thấy sách nào.</p>
        </div>
    {% endfor %}
</div>

<!-- Phan trang -->
<div class="flex justify-center mt-10">
    <nav class="flex items-center space-x-1 sm:space-x-2">
        <a href="{{ url_for(request.endpoint, page=pagination.prev_num, q=query, user_id=request.view_args.get('user_id'), list_id=request.view_args.get('list_id')) if pagination.has_prev else '#' }}" class="px-3 py-2 sm:px-4 bg-white dark:bg-gray-700 rounded-lg {% if not pagination.has_prev %}opacity-50 cursor-not-allowed{% else %}hover:bg-gray-200 dark:hover:bg-gray-600{% endif %}">
            <i class="fas fa-arrow-left"></i>
        </a>
        {% for p in pagination.iter_pages(left_edge=1, right_edge=1, left_current=1, right_current=1) %}
            {% if p %}
                <a href="{{ url_for(request.endpoint, page=p, q=query, user_id=request.view_args.get('user_id'), list_id=request.view_args.get('list_id')) }}" class="px-3 py-2 sm:px-4 rounded-lg {% if p == pagination.page %}bg-theme-600 text-white{% else %}bg-white dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600{% endif %}">{{ p }}</a>
            {% else %}
                <span class="px-3 py-2 sm:px-4 text-gray-500 hidden sm:inline">...</span>
            {% endif %}
        {% endfor %}
        <a href="{{ url_for(request.endpoint, page=pagination.next_num, q=query, user_id=request.view_args.get('user_id'), list_id=request.view_args.get('list_id')) if pagination.has_next else '#' }}" class="px-3 py-2 sm:px-4 bg-white dark:bg-gray-700 rounded-lg {% if not pagination.has_next %}opacity-50 cursor-not-allowed{% else %}hover:bg-gray-200 dark:hover:bg-gray-600{% endif %}">
            <i class="fas fa-arrow-right"></i>
        </a>
    </nav>
</div>
"""

BOOK_DETAIL_TEMPLATE = """
<div class="flex flex-col md:flex-row gap-8">
    <div class="w-full md:w-1/3 lg:w-1/4 mx-auto md:mx-0 max-w-xs">
        <a href="{{ url_for('cover_original', book_id=book.id) }}" target="_blank">
            <img src="{{ url_for('cover', book_id=book.id) }}" 
                 alt="Bìa sách {{ book.title }}" 
                 class="rounded-lg shadow-2xl w-full"
                 onerror="this.onerror=null; this.src='{{ url_for('static', filename='default_cover.jpg') }}';">
        </a>
    </div>

    <div class="w-full md:w-2/3 lg:w-3/4">
        <h2 class="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white">{{ book.title }}</h2>
        <a href="{{ url_for('index', q=book.author) }}" class="text-lg md:text-xl text-gray-500 dark:text-gray-400 hover:text-theme-600 dark:hover:text-theme-400">{{ book.author }}</a>
        
        <div id="rating-stars" class="flex items-center my-3 text-2xl {% if session.get('username') == GUEST_USERNAME and not guest_permissions.can_rate %}pointer-events-none opacity-50{% endif %}">
            {% for i in range(1, 6) %}
                <i class="fas fa-star cursor-pointer interactive-star {% if book.rating and book.rating >= i %}text-yellow-400{% else %}text-gray-400 dark:text-gray-600{% endif %}" 
                   data-rating="{{ i }}"
                   onclick="rateBook({{ book.id }}, {{ i }})"></i>
            {% endfor %}
        </div>
        
        <div class="my-6 flex flex-wrap gap-2">
            <!-- Nút đọc sách -->
            {% if epub_book %}
                <a href="{{ url_for('read_online', book_id=epub_book.id) }}" class="px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center">
                    <i class="fas fa-book-open mr-2"></i> Đọc sách
                </a>
            {% else %}
                <button class="px-3 py-2 bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 rounded-lg cursor-not-allowed flex items-center" disabled title="Không có định dạng EPUB để đọc online">
                    <i class="fas fa-book-open mr-2"></i> Đọc sách
                </button>
            {% endif %}

            <!-- Nút tải về (Dropdown) -->
            <div x-data="{ open: false }" class="relative">
                <button @click="open = !open" class="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center">
                    <i class="fas fa-download mr-2"></i> Tải về
                    <i class="fas fa-chevron-down ml-2 text-xs transition-transform" :class="{'rotate-180': open}"></i>
                </button>
                <div x-show="open" @click.away="open = false" 
                     x-transition:enter="transition ease-out duration-100" x-transition:enter-start="transform opacity-0 scale-95" x-transition:enter-end="transform opacity-100 scale-100"
                     x-transition:leave="transition ease-in duration-75" x-transition:leave-start="transform opacity-100 scale-100" x-transition:leave-end="transform opacity-0 scale-95"
                     class="absolute left-0 mt-2 w-56 rounded-md shadow-lg bg-white dark:bg-gray-800 ring-1 ring-black ring-opacity-5 focus:outline-none z-10" x-cloak>
                    <div class="py-1" role="none">
                        {% for b in all_formats %}
                        <div class="flex items-center justify-between px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600">
                            <span class="font-semibold">{{ b.format.upper() }}</span>
                            <div class="flex items-center gap-3">
                                <a href="{{ url_for('read', book_id=b.id) }}" title="Tải về {{ b.format.upper() }}" class="text-blue-500 hover:text-blue-400"><i class="fas fa-download"></i></a>
                                <form action="{{ url_for('delete_format', book_id=b.id) }}" method="POST" onsubmit="return confirm('Bạn có chắc muốn xóa định dạng {{ b.format.upper() }} này không?')">
                                    <button type="submit" title="Xóa định dạng {{ b.format.upper() }}" class="text-red-500 hover:text-red-400"><i class="fas fa-trash"></i></button>
                                </form>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <button onclick="openListManagerModal({{ book.id }})" class="px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors flex items-center">
                <i class="fas fa-plus mr-2"></i> Thêm vào kệ
            </button>

            {% if session.get('username') != GUEST_USERNAME or (guest_permissions and guest_permissions.can_favorite) %}
            <button onclick="toggleFavorite({{ book.id }})" id="favorite-btn" class="px-3 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors flex items-center">
                <i id="favorite-icon" class="{% if is_favorited %}fas fa-heart text-red-500{% else %}far fa-heart{% endif %} mr-2"></i> 
                <span id="favorite-text">{% if is_favorited %}Bỏ thích{% else %}Yêu thích{% endif %}</span>
            </button>
            {% endif %}

            {% if session.get('username') != GUEST_USERNAME or (guest_permissions and guest_permissions.can_bookmark) %}
            <button onclick="toggleBookmark({{ book.id }})" id="bookmark-btn" class="px-3 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors flex items-center">
                <i id="bookmark-icon" class="{% if is_bookmarked %}fas fa-bookmark text-theme-500{% else %}far fa-bookmark{% endif %} mr-2"></i> 
                <span id="bookmark-text">{% if is_bookmarked %}Bỏ đánh dấu{% else %}Đánh dấu{% endif %}</span>
            </button>
            {% endif %}

            {% if session.get('is_admin') or (book.user_id == session.get('user_id')) %}
                <button onclick="document.getElementById('convert-modal').classList.remove('hidden')" class="px-3 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors flex items-center">
                    <i class="fas fa-sync-alt mr-2"></i> Chuyển đổi
                </button>
                <a href="{{ url_for('edit', book_id=book.id) }}" class="px-3 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors flex items-center"><i class="fas fa-edit mr-2"></i> Sửa</a>
                <a href="{{ url_for('delete', book_id=book.id) }}" onclick="return confirm('Bạn có chắc chắn muốn xóa sách này và TẤT CẢ các định dạng của nó?')" class="px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors flex items-center"><i class="fas fa-trash mr-2"></i> Xóa</a>
            {% endif %}
        </div>

        <h3 class="text-xl font-semibold text-gray-900 dark:text-white mt-8 mb-2">Mô tả</h3>
        <p class="text-gray-700 dark:text-gray-300 leading-relaxed">{{ book.description or 'Chưa có mô tả cho sách này.' }}</p>
        
        <div class="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div><strong class="text-gray-500 dark:text-gray-400">Nhà xuất bản:</strong> {{ book.publisher or 'N/A' }}</div>
            <div><strong class="text-gray-500 dark:text-gray-400">Ngày xuất bản:</strong> {{ book.pubdate or 'N/A' }}</div>
            <div><strong class="text-gray-500 dark:text-gray-400">Ngôn ngữ:</strong> {{ book.language or 'N/A' }}</div>
            {% if book.series %}
            <div>
                <strong class="text-gray-500 dark:text-gray-400">Bộ truyện:</strong> <a href="{{ url_for('index', q=book.series) }}" class="hover:text-theme-600 dark:hover:text-theme-400">{{ book.series }}</a>
                <strong class="ml-4">Tập số:</strong> {{ book.series_index | int }}
            </div>
            {% endif %}
        </div>

        <h3 class="text-xl font-semibold text-gray-900 dark:text-white mt-8 mb-2">Thể loại</h3>
        <div class="flex flex-wrap gap-2">
            {% for tag in (book.tags or '').split(',') %}
                {% if tag.strip() %}
                <a href="{{ url_for('index', q=tag.strip()) }}" class="bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-sm px-3 py-1 rounded-full hover:bg-theme-100 dark:hover:bg-theme-800 hover:text-theme-800 dark:hover:text-theme-200 transition-colors">{{ tag.strip() }}</a>
                {% endif %}
            {% endfor %}
        </div>
    </div>
</div>

<div class="mt-12">
    <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Sách liên quan</h2>
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 md:gap-6">
        {% for related_book in related_books %}
            <div class="book-card bg-white dark:bg-gray-800 rounded-lg overflow-hidden shadow-lg hover:shadow-xl dark:hover:shadow-theme-800/20 transition-shadow duration-300 group">
                <a href="{{ url_for('book_detail', book_id=related_book.id) }}">
                    <img src="{{ url_for('cover', book_id=related_book.id) }}" 
                         loading="lazy"
                         class="book-cover" 
                         alt="Bìa sách {{ related_book.title }}"
                         onerror="this.onerror=null; this.src='{{ url_for('static', filename='default_cover.jpg') }}';">
                </a>
                <div class="p-3">
                    <a href="{{ url_for('book_detail', book_id=related_book.id) }}">
                        <h3 class="font-bold text-gray-800 dark:text-white truncate group-hover:text-theme-600 dark:group-hover:text-theme-400">{{ related_book.title }}</h3>
                    </a>
                    <p class="text-sm text-gray-500 dark:text-gray-400 truncate">{{ related_book.author }}</p>
                </div>
            </div>
        {% else %}
             <p class="col-span-full text-gray-500 dark:text-gray-400">Không có sách nào liên quan.</p>
        {% endfor %}
    </div>
</div>

<!-- Modals -->
<div id="convert-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center hidden z-50 p-4">
    <div class="bg-white dark:bg-gray-800 rounded-lg p-8 max-w-sm w-full">
        <h3 class="text-xl font-bold text-gray-900 dark:text-white mb-4">Chuyển đổi sách</h3>
        <p class="text-gray-500 dark:text-gray-400 mb-6">Chọn định dạng bạn muốn chuyển đổi sang:</p>
        <form action="{{ url_for('convert_book', book_id=book.id) }}" method="POST">
            <select name="target_format" class="w-full bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg p-3 mb-6 focus:outline-none focus:ring-2 focus:ring-theme-500">
                {% for fmt in ['epub', 'mobi', 'pdf', 'azw3'] %}
                    {% if fmt != book.format %}
                        <option value="{{ fmt }}">{{ fmt.upper() }}</option>
                    {% endif %}
                {% endfor %}
            </select>
            <div class="flex justify-end space-x-4">
                <button type="button" onclick="document.getElementById('convert-modal').classList.add('hidden')" class="px-4 py-2 bg-gray-500 text-white rounded-lg hover:bg-gray-600">Hủy</button>
                <button type="submit" class="px-4 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700">Chuyển đổi</button>
            </div>
        </form>
    </div>
</div>

<div id="list-manager-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center hidden z-50 p-4">
    <div class="bg-white dark:bg-gray-800 rounded-lg p-6 max-w-md w-full">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-xl font-bold text-gray-900 dark:text-white">Thêm/Xóa khỏi kệ sách</h3>
            <button onclick="document.getElementById('list-manager-modal').classList.add('hidden')" class="text-gray-400 hover:text-gray-800 dark:hover:text-white text-2xl">&times;</button>
        </div>
        <div id="list-manager-content" class="space-y-2 max-h-60 overflow-y-auto mb-4"></div>
        <hr class="border-gray-200 dark:border-gray-600 my-4">
        <form id="add-list-from-modal-form">
            <label for="add-list-name" class="block text-gray-500 dark:text-gray-400 mb-2">Hoặc tạo kệ sách mới</label>
            <div class="flex gap-2">
                <input type="text" id="add-list-name" name="name" class="flex-grow bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-theme-500" placeholder="Tên kệ sách mới" required>
                <button type="submit" class="px-4 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700">Tạo</button>
            </div>
        </form>
    </div>
</div>

<script>
function toggleFavorite(bookId) {
    fetch(`/toggle_favorite/${bookId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const favoriteIcon = document.getElementById('favorite-icon');
                const favoriteText = document.getElementById('favorite-text');
                if (data.status === 'added') {
                    favoriteText.innerText = 'Bỏ thích';
                    favoriteIcon.classList.remove('far');
                    favoriteIcon.classList.add('fas', 'text-red-500');
                } else {
                    favoriteText.innerText = 'Yêu thích';
                    favoriteIcon.classList.remove('fas', 'text-red-500');
                    favoriteIcon.classList.add('far');
                }
            } else {
                alert('Đã có lỗi xảy ra: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Fetch Error:', error);
            alert('Lỗi kết nối. Vui lòng thử lại.');
        });
}

function toggleBookmark(bookId) {
    fetch(`/toggle_bookmark/${bookId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const bookmarkIcon = document.getElementById('bookmark-icon');
                const bookmarkText = document.getElementById('bookmark-text');
                if (data.status === 'added') {
                    bookmarkText.innerText = 'Bỏ đánh dấu';
                    bookmarkIcon.classList.remove('far');
                    bookmarkIcon.classList.add('fas', 'text-theme-500');
                } else {
                    bookmarkText.innerText = 'Đánh dấu';
                    bookmarkIcon.classList.remove('fas', 'text-theme-500');
                    bookmarkIcon.classList.add('far');
                }
            } else {
                alert('Đã có lỗi xảy ra: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Fetch Error:', error);
            alert('Lỗi kết nối. Vui lòng thử lại.');
        });
}

function rateBook(bookId, rating) {
    fetch(`/rate_book/${bookId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: rating }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const stars = document.querySelectorAll('#rating-stars .fa-star');
            stars.forEach(star => {
                const starRating = parseInt(star.dataset.rating, 10);
                if (starRating <= rating) {
                    star.classList.remove('text-gray-400', 'dark:text-gray-600');
                    star.classList.add('text-yellow-400');
                } else {
                    star.classList.remove('text-yellow-400');
                    star.classList.add('text-gray-400', 'dark:text-gray-600');
                }
            });
        } else {
            alert('Đã có lỗi xảy ra: ' + data.message);
        }
    });
}

let currentBookIdForLists = null;

function openListManagerModal(bookId) {
    currentBookIdForLists = bookId;
    const modal = document.getElementById('list-manager-modal');
    const contentDiv = document.getElementById('list-manager-content');
    contentDiv.innerHTML = '<p class="text-gray-500 dark:text-gray-400">Đang tải...</p>';
    modal.classList.remove('hidden');

    fetch(`/api/book/${bookId}/lists`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                contentDiv.innerHTML = '';
                if (data.lists.length === 0) {
                     contentDiv.innerHTML = '<p class="text-gray-500 dark:text-gray-400">Bạn chưa có kệ sách nào.</p>';
                }
                data.lists.forEach(list => {
                    const isChecked = list.has_book ? 'checked' : '';
                    const label = document.createElement('label');
                    label.className = 'flex items-center p-2 bg-gray-100 dark:bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600';
                    label.innerHTML = `
                        <input type="checkbox" onchange="toggleBookInList(${bookId}, ${list.id}, this.checked)" ${isChecked} class="h-5 w-5 rounded bg-gray-300 dark:bg-gray-900 border-gray-400 dark:border-gray-600 text-theme-600 focus:ring-theme-500">
                        <span class="ml-3 text-gray-800 dark:text-gray-300">${list.name}</span>
                    `;
                    contentDiv.appendChild(label);
                });
            } else {
                contentDiv.innerHTML = '<p class="text-red-500">Lỗi tải danh sách.</p>';
            }
        });
}

function toggleBookInList(bookId, listId, shouldAdd) {
    fetch('/api/lists/toggle_book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ book_id: bookId, list_id: listId, action: shouldAdd ? 'add' : 'remove' }),
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            alert('Lỗi: ' + data.message);
            openListManagerModal(bookId); 
        }
    });
}

document.getElementById('add-list-from-modal-form').addEventListener('submit', function(e) {
    e.preventDefault();
    const listNameInput = document.getElementById('add-list-name');
    const listName = listNameInput.value;
    if (!listName) return;

    fetch('{{ url_for("create_list") }}', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: listName }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            listNameInput.value = '';
            openListManagerModal(currentBookIdForLists);
        } else {
            alert('Lỗi: ' + data.message);
        }
    });
});
</script>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng nhập - {{ app_config.library_name }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-900 font-sans flex items-center justify-center min-h-screen p-4">
    <div class="w-full max-w-sm">
        <div class="bg-gray-800 rounded-xl shadow-2xl p-8">
            <h2 class="text-3xl font-bold text-center mb-6 text-white flex items-center justify-center">
                <i class="fas fa-book-open text-cyan-400 mr-2"></i> Đăng nhập
            </h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="bg-{{ 'green' if category=='success' else 'red' }}-600 text-white p-4 rounded-lg mb-4">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="post" class="space-y-4">
                <div>
                    <input name="username" class="w-full px-4 py-3 bg-gray-700 text-white rounded-lg border border-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500" placeholder="Tên đăng nhập" required>
                </div>
                <div>
                    <input name="password" type="password" class="w-full px-4 py-3 bg-gray-700 text-white rounded-lg border border-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500" placeholder="Mật khẩu">
                </div>
                <button class="w-full px-4 py-3 bg-cyan-600 text-white font-bold rounded-lg hover:bg-cyan-700 transition-colors">Đăng nhập</button>
            </form>
            <p class="mt-4 text-center text-gray-400">Hoặc đăng nhập với tư cách <strong>{{ GUEST_USERNAME }}</strong> (không cần mật khẩu).</p>
            <p class="mt-6 text-center text-gray-400">Chưa có tài khoản? <a href="{{ url_for('register') }}" class="text-cyan-400 hover:underline">Đăng ký tại đây</a></p>
        </div>
    </div>
</body>
</html>
"""

REGISTER_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng ký - {{ app_config.library_name }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-900 font-sans flex items-center justify-center min-h-screen p-4">
    <div class="w-full max-w-sm">
        <div class="bg-gray-800 rounded-xl shadow-2xl p-8">
            <h2 class="text-3xl font-bold text-center mb-6 text-white">Đăng ký tài khoản</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="bg-red-600 text-white p-4 rounded-lg mb-4">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <form method="post" class="space-y-4">
                <div>
                    <input name="username" class="w-full px-4 py-3 bg-gray-700 text-white rounded-lg border border-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500" placeholder="Tên đăng nhập" required>
                </div>
                <div>
                    <input name="password" type="password" class="w-full px-4 py-3 bg-gray-700 text-white rounded-lg border border-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500" placeholder="Mật khẩu" required>
                </div>
                <button class="w-full px-4 py-3 bg-cyan-600 text-white font-bold rounded-lg hover:bg-cyan-700 transition-colors">Đăng ký</button>
            </form>
            <p class="mt-6 text-center text-gray-400">Đã có tài khoản? <a href="{{ url_for('login') }}" class="text-cyan-400 hover:underline">Đăng nhập</a></p>
        </div>
    </div>
</body>
</html>
"""

CHANGE_PASSWORD_TEMPLATE = """
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-8 max-w-md mx-auto">
    <h2 class="text-2xl font-bold text-center mb-6 text-gray-900 dark:text-white">Đổi mật khẩu</h2>
    <form method="post" class="space-y-4">
        <div>
            <label for="current_password" class="block text-gray-600 dark:text-gray-400 font-bold mb-1">Mật khẩu hiện tại</label>
            <input name="current_password" id="current_password" type="password" class="w-full px-4 py-3 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" required>
        </div>
        <div>
            <label for="new_password" class="block text-gray-600 dark:text-gray-400 font-bold mb-1">Mật khẩu mới</label>
            <input name="new_password" id="new_password" type="password" class="w-full px-4 py-3 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" required>
        </div>
        <div>
            <label for="confirm_password" class="block text-gray-600 dark:text-gray-400 font-bold mb-1">Xác nhận mật khẩu mới</label>
            <input name="confirm_password" id="confirm_password" type="password" class="w-full px-4 py-3 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" required>
        </div>
        <button class="w-full px-4 py-3 bg-theme-600 text-white font-bold rounded-lg hover:bg-theme-700 transition-colors">Cập nhật mật khẩu</button>
    </form>
</div>
"""

USER_MANAGEMENT_TEMPLATE = """
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-4 md:p-6 mx-auto">
    <h2 class="text-2xl font-bold mb-6 text-gray-900 dark:text-white">Quản lý người dùng</h2>
    <div class="overflow-x-auto">
        <table class="min-w-full bg-white dark:bg-gray-800 text-gray-900 dark:text-white">
            <thead class="bg-gray-50 dark:bg-gray-700">
                <tr>
                    <th class="py-3 px-4 text-left">Tên người dùng</th>
                    <th class="py-3 px-4 text-left hidden sm:table-cell">Số sách</th>
                    <th class="py-3 px-4 text-center">Hành động</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
                {% for user in users %}
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td class="py-3 px-4">
                        {{ user.username }}
                        {% if user.is_admin %}
                            <span class="ml-2 px-2 py-1 bg-green-600 text-white text-xs rounded-full">Admin</span>
                        {% endif %}
                    </td>
                    <td class="py-3 px-4 hidden sm:table-cell">{{ user.books|length }}</td>
                    <td class="py-3 px-4 text-center">
                        {% if user.id != session.get('user_id') and user.username not in [GUEST_USERNAME, ADMIN_USERNAME] %}
                        <div class="flex flex-col sm:flex-row gap-2 justify-center">
                            <form method="POST" action="{{ url_for('toggle_admin', user_id=user.id) }}" class="inline-block">
                                <button type="submit" class="w-full text-sm px-3 py-1 rounded-lg {{ 'bg-yellow-600 hover:bg-yellow-700' if user.is_admin else 'bg-green-600 hover:bg-green-700' }} text-white transition-colors">
                                    {% if user.is_admin %}Hủy Admin{% else %}Gán Admin{% endif %}
                                </button>
                            </form>
                            <form method="POST" action="{{ url_for('delete_user', user_id=user.id) }}" class="inline-block" onsubmit="return confirm('Bạn có chắc chắn muốn xóa người dùng này? Thao tác này sẽ xóa TOÀN BỘ sách của họ.');">
                                <button type="submit" class="w-full text-sm px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-white transition-colors">Xóa</button>
                            </form>
                        </div>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

GUEST_PERMISSIONS_TEMPLATE = """
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-8 max-w-lg mx-auto">
    <h2 class="text-2xl font-bold mb-6 text-gray-900 dark:text-white">Cài đặt quyền cho tài khoản Khách</h2>
    <form method="POST">
        <div class="space-y-6">
            <label class="flex items-center p-4 bg-gray-100 dark:bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors">
                <input type="checkbox" name="can_favorite" class="h-6 w-6 rounded bg-gray-300 dark:bg-gray-900 border-gray-400 dark:border-gray-600 text-theme-600 focus:ring-theme-500" {% if permissions.can_favorite %}checked{% endif %}>
                <span class="ml-4 text-lg text-gray-700 dark:text-gray-300">Cho phép yêu thích sách</span>
            </label>
            <label class="flex items-center p-4 bg-gray-100 dark:bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors">
                <input type="checkbox" name="can_bookmark" class="h-6 w-6 rounded bg-gray-300 dark:bg-gray-900 border-gray-400 dark:border-gray-600 text-theme-600 focus:ring-theme-500" {% if permissions.can_bookmark %}checked{% endif %}>
                <span class="ml-4 text-lg text-gray-700 dark:text-gray-300">Cho phép đánh dấu sách</span>
            </label>
            <label class="flex items-center p-4 bg-gray-100 dark:bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors">
                <input type="checkbox" name="can_rate" class="h-6 w-6 rounded bg-gray-300 dark:bg-gray-900 border-gray-400 dark:border-gray-600 text-theme-600 focus:ring-theme-500" {% if permissions.can_rate %}checked{% endif %}>
                <span class="ml-4 text-lg text-gray-700 dark:text-gray-300">Cho phép đánh giá sách</span>
            </label>
            <label class="flex items-center p-4 bg-gray-100 dark:bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors">
                <input type="checkbox" name="can_upload_books" class="h-6 w-6 rounded bg-gray-300 dark:bg-gray-900 border-gray-400 dark:border-gray-600 text-theme-600 focus:ring-theme-500" {% if permissions.can_upload_books %}checked{% endif %}>
                <span class="ml-4 text-lg text-gray-700 dark:text-gray-300">Cho phép tải lên / nhập sách</span>
            </label>
        </div>
        <div class="mt-8">
            <button type="submit" class="w-full px-4 py-3 bg-theme-600 text-white font-bold rounded-lg hover:bg-theme-700 transition-colors">
                <i class="fas fa-save mr-2"></i> Lưu thay đổi
            </button>
        </div>
    </form>
</div>
"""

EDIT_TEMPLATE = """
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 md:p-8 mx-auto">
    <h2 class="text-2xl font-bold mb-6 text-gray-900 dark:text-white">Sửa thông tin sách</h2>
    <form method="POST" enctype="multipart/form-data">
        <div class="flex flex-col md:flex-row gap-8">
            <div class="w-full md:w-1/3 mx-auto md:mx-0 max-w-xs">
                <img id="cover_preview" src="{{ url_for('cover', book_id=book.id) }}" alt="Bìa sách" class="rounded-lg shadow-lg w-full mb-4" onerror="this.onerror=null; this.src='{{ url_for('static', filename='default_cover.jpg') }}';">
                <label class="block w-full text-center px-3 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-white rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors cursor-pointer">
                    <i class="fas fa-camera mr-2"></i> Chọn ảnh bìa mới
                    <input type="file" name="cover_image" class="hidden" accept="image/*" onchange="previewCover(event)">
                </label>
            </div>
            <div class="w-full md:w-2/3 space-y-4">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="title" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Tựa sách</label>
                        <input name="title" id="title" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.title or '' }}">
                    </div>
                    <div>
                        <label for="author" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Tác giả</label>
                        <input name="author" id="author" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.author or '' }}">
                    </div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                     <div>
                        <label for="series" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Bộ truyện</label>
                        <input name="series" id="series" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.series or '' }}">
                    </div>
                    <div>
                        <label for="series_index" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Tập số</label>
                        <input name="series_index" type="number" step="1" min="1" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ (book.series_index | int) if book.series_index else 1 }}">
                    </div>
                </div>
                 <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label for="publisher" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Nhà xuất bản</label>
                        <input name="publisher" id="publisher" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.publisher or '' }}">
                    </div>
                    <div>
                        <label for="pubdate" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Ngày xuất bản</label>
                        <input name="pubdate" id="pubdate" type="date" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.pubdate or '' }}">
                    </div>
                </div>
                <div>
                    <label for="language" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Ngôn ngữ</label>
                    <input name="language" id="language" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.language or 'Tiếng Việt' }}">
                </div>
                <div>
                    <label class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Điểm số</label>
                    <div class="star-rating flex items-center flex-row-reverse justify-end">
                        {% for i in range(5, 0, -1) %}
                        <input type="radio" id="star{{i}}" name="rating" value="{{i}}" {% if book.rating == i %}checked{% endif %} class="hidden"/>
                        <label for="star{{i}}" class="text-2xl cursor-pointer text-gray-400 dark:text-gray-600 hover:text-yellow-400 transition-colors"><i class="fas fa-star"></i></label>
                        {% endfor %}
                    </div>
                </div>
                <div>
                    <label for="tags" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Thể loại (cách nhau bằng dấu phẩy)</label>
                    <input name="tags" id="tags" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500" value="{{ book.tags or '' }}">
                </div>
                <div>
                    <label for="description" class="block text-gray-500 dark:text-gray-400 font-bold mb-1">Mô tả</label>
                    <textarea name="description" id="description" rows="4" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500">{{ book.description or '' }}</textarea>
                </div>
            </div>
        </div>
        <div class="flex flex-col sm:flex-row space-y-2 sm:space-y-0 sm:space-x-4 pt-8">
            <button type="submit" class="flex-1 px-4 py-3 bg-theme-600 text-white font-bold rounded-lg hover:bg-theme-700 transition-colors"><i class="fas fa-save mr-2"></i> Lưu thay đổi</button>
            <a href="{{ url_for('book_detail', book_id=book.id) }}" class="flex-1 text-center px-4 py-3 bg-gray-600 text-white font-bold rounded-lg hover:bg-gray-500 transition-colors"><i class="fas fa-times mr-2"></i> Hủy</a>
        </div>
    </form>
</div>
<style>
.star-rating > input:checked ~ label,
.star-rating:not(:checked) > label:hover,
.star-rating:not(:checked) > label:hover ~ label { color: #f59e0b; }
.star-rating > input:checked + label:hover,
.star-rating > input:checked ~ label:hover,
.star-rating > label:hover ~ input:checked ~ label,
.star-rating > input:checked ~ label:hover ~ label { color: #d97706; }
</style>
<script>
function previewCover(event) {
    const reader = new FileReader();
    reader.onload = function(){
        document.getElementById('cover_preview').src = reader.result;
    };
    reader.readAsDataURL(event.target.files[0]);
}
</script>
"""

EPUB_READER_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ book.title }} - Trình đọc sách</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.1.5/jszip.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/epubjs/dist/epub.min.js"></script>
    <style>
        body { overflow: hidden; }
        #viewer-container { position: relative; width: 100%; flex-grow: 1; }
        #viewer {
            height: 100%;
            width: 100%;
            padding: 0 1rem;
        }
        @media (min-width: 768px) {
             #viewer { padding: 0 2rem; }
        }
        #viewer.paginated { overflow: hidden; }
        #main-sidebar { transition: transform 0.3s ease-in-out; }
        .sidebar-content-item { display: block; padding: 0.6rem 1rem; border-bottom: 1px solid #374151; cursor: pointer; }
        .sidebar-content-item:hover { background-color: #374151; }
        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: #1f2937; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 3px; }
    </style>
</head>
<body class="bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-200">
    <div id="reader-ui" class="flex flex-col h-screen">
        <!-- Top Bar -->
        <header class="bg-gray-200 dark:bg-gray-800 p-2 flex items-center justify-between text-black dark:text-white shadow-md z-20 w-full">
            <a href="{{ url_for('book_detail', book_id=book.id) }}" class="text-xl px-2 hover:text-cyan-400 transition-colors">
                <i class="fas fa-arrow-left"></i>
            </a>
            <h1 class="text-base sm:text-lg font-bold truncate mx-2 text-center flex-grow">{{ book.title }}</h1>
            <div class="flex items-center space-x-2 sm:space-x-4">
                <button id="search-btn" title="Tìm kiếm" class="text-xl px-2 hover:text-cyan-400"><i class="fas fa-search"></i></button>
                <button id="settings-btn" title="Cài đặt" class="text-xl px-2 hover:text-cyan-400"><i class="fas fa-cog"></i></button>
                <button id="sidebar-btn" title="Mục lục" class="text-xl px-2 hover:text-cyan-400"><i class="fas fa-bars"></i></button>
            </div>
        </header>

        <!-- Main Viewer Area -->
        <div id="viewer-container">
            <div id="viewer" class="w-full h-full paginated"></div>
            <div id="prev" class="absolute left-0 top-0 h-full w-1/4 cursor-pointer z-10"></div>
            <div id="next" class="absolute right-0 top-0 h-full w-1/4 cursor-pointer z-10"></div>
             <div id="loader" class="absolute inset-0 bg-gray-900 bg-opacity-75 flex items-center justify-center z-50">
                <div class="text-white text-2xl">
                    <i class="fas fa-spinner fa-spin mr-3"></i> Đang tải sách...
                </div>
            </div>
        </div>

        <!-- Bottom Bar -->
        <footer class="bg-gray-200 dark:bg-gray-800 p-2 flex items-center justify-between text-black dark:text-white shadow-md z-20">
            <span id="progress" class="text-sm ml-2">Trang 1/1</span>
            <div class="flex items-center">
                <label for="goto-input" class="text-sm mr-2 hidden sm:inline">Đi tới trang:</label>
                <input type="text" id="goto-input" class="bg-gray-300 dark:bg-gray-700 rounded-l-md w-20 text-center py-1" placeholder="Trang...">
                <button id="goto-btn" class="bg-cyan-600 px-3 py-1 rounded-r-md text-white hover:bg-cyan-700"><i class="fas fa-arrow-right"></i></button>
            </div>
        </footer>

        <!-- Main Sidebar (TOC) -->
        <aside id="main-sidebar" class="fixed top-0 right-0 h-full w-80 max-w-full bg-gray-200 dark:bg-gray-800 shadow-lg z-30 transform translate-x-full custom-scrollbar">
            <div class="flex justify-between items-center p-2 border-b border-gray-300 dark:border-gray-700">
                <h2 class="text-xl font-bold">Mục lục</h2>
                <button id="close-sidebar" class="text-2xl px-2">&times;</button>
            </div>
            <div id="toc-panel" class="overflow-y-auto h-[calc(100%-3.5rem)]"></div>
        </aside>

        <!-- Modals -->
        <div id="settings-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center hidden z-40 p-4">
            <div class="bg-gray-200 dark:bg-gray-800 rounded-lg p-6 max-w-sm w-full relative">
                <button id="close-settings" class="absolute top-3 right-4 text-2xl">&times;</button>
                <h3 class="text-xl font-bold mb-6">Cài đặt hiển thị</h3>
                <div class="mb-4">
                    <label class="block mb-2">Cỡ chữ</label>
                    <div class="flex items-center"><input id="font-size-slider" type="range" min="80" max="200" value="100" class="w-full"></div>
                </div>
                <div class="mb-4">
                    <label for="font-family-select" class="block mb-2">Phông chữ</label>
                    <select id="font-family-select" class="w-full p-2 rounded bg-gray-300 dark:bg-gray-700">
                        <option value="Georgia, serif">Georgia (Serif)</option>
                        <option value="Arial, sans-serif">Arial (Sans-Serif)</option>
                    </select>
                </div>
                <div class="mb-4">
                    <label for="bgColorInput" class="block mb-2">Màu nền tùy chỉnh</label>
                    <input type="color" id="bgColorInput" class="w-full h-10 p-1 bg-gray-300 dark:bg-gray-700 rounded-lg cursor-pointer border-2 border-gray-400">
                </div>
            </div>
        </div>
        
        <div id="search-modal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center hidden z-40 p-4">
            <div class="bg-gray-200 dark:bg-gray-800 rounded-lg p-4 max-w-lg w-full h-3/4 flex flex-col">
                 <div class="flex justify-between items-center mb-4">
                    <h3 class="text-xl font-bold">Tìm kiếm</h3>
                    <button id="close-search" class="text-2xl">&times;</button>
                </div>
                <div class="flex mb-4">
                    <input type="text" id="search-input" class="w-full p-2 rounded-l bg-gray-300 dark:bg-gray-700 focus:outline-none" placeholder="Nhập để tìm kiếm...">
                    <button id="do-search-btn" class="bg-cyan-600 px-4 rounded-r hover:bg-cyan-700"><i class="fas fa-search"></i></button>
                </div>
                <div id="search-results" class="flex-grow overflow-y-auto custom-scrollbar"></div>
            </div>
        </div>
    </div>

    <script>
        const bookPath = "{{ url_for('serve_book_file', book_id=book.id) }}";
        const bookId = {{ book.id }};
        const initialSettings = JSON.parse('{{ settings_json | safe }}' || '{}');
        
        // DOM Elements
        const viewerDiv = document.getElementById('viewer');
        const loader = document.getElementById('loader');
        const sidebarBtn = document.getElementById('sidebar-btn');
        const closeSidebarBtn = document.getElementById('close-sidebar');
        const mainSidebar = document.getElementById('main-sidebar');
        const tocPanel = document.getElementById('toc-panel');
        const settingsBtn = document.getElementById('settings-btn');
        const closeSettingsBtn = document.getElementById('close-settings');
        const settingsModal = document.getElementById('settings-modal');
        const searchBtn = document.getElementById('search-btn');
        const closeSearchBtn = document.getElementById('close-search');
        const searchModal = document.getElementById('search-modal');
        const doSearchBtn = document.getElementById('do-search-btn');
        const searchInput = document.getElementById('search-input');
        const searchResultsContainer = document.getElementById('search-results');
        const prevBtn = document.getElementById('prev');
        const nextBtn = document.getElementById('next');
        const progressSpan = document.getElementById('progress');
        const gotoInput = document.getElementById('goto-input');
        const gotoBtn = document.getElementById('goto-btn');

        // Settings Elements
        const fontSizeSlider = document.getElementById('font-size-slider');
        const fontFamilySelect = document.getElementById('font-family-select');
        const bgColorInput = document.getElementById('bgColorInput');

        let userSettings = { fontSize: 100, fontFamily: 'Georgia, serif', bgColor: '#111827' };
        Object.assign(userSettings, initialSettings);

        let book, rendition;
        let isProgrammaticNavigation = false;
        
        // API Helper
        async function apiCall(endpoint, method = 'GET', body = null) {
            try {
                const options = {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                };
                if (body) {
                    options.body = JSON.stringify(body);
                }
                const response = await fetch(endpoint, options);
                if (!response.ok) {
                    const err = await response.json().catch(() => ({ message: response.statusText }));
                    console.error(`API Error: ${response.status} ${err.message}`);
                    alert(`Lỗi: ${err.message || response.statusText}`);
                    return null;
                }
                return response.json();
            } catch (error) {
                console.error('Fetch API Error:', error);
                return null;
            }
        }

        function navigateTo(cfi) {
            if (!rendition || !cfi) return;
            isProgrammaticNavigation = true;
            rendition.display(cfi).then(() => {
                localStorage.setItem(`kavita-progress-${book.key()}`, rendition.currentLocation().start.cfi);
                isProgrammaticNavigation = false;
            }).catch(err => {
                console.error("Lỗi điều hướng:", err);
                isProgrammaticNavigation = false;
            });
        }

        // Main function
        async function main() {
            try {
                const response = await fetch(bookPath);
                const buffer = await response.arrayBuffer();
                book = ePub(buffer);
                rendition = book.renderTo("viewer", {
                    width: "100%", height: "100%",
                    flow: "paginated", spread: "auto"
                });

                setupEventListeners();
                
                await book.ready;
                await book.locations.generate(1600);
                
                setupToc();
                applySettings();
                
                const lastLocation = localStorage.getItem(`kavita-progress-${book.key()}`);
                rendition.display(lastLocation || undefined);

            } catch (error) {
                console.error("Lỗi khi tải sách:", error);
                loader.innerHTML = '<div class="text-white text-2xl text-red-500">Lỗi tải sách.</div>';
            }
        }

        function setupEventListeners() {
            prevBtn.addEventListener('click', () => rendition.prev());
            nextBtn.addEventListener('click', () => rendition.next());
            document.addEventListener('keydown', (e) => {
                if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
                if (e.key === 'ArrowLeft') rendition.prev();
                if (e.key === 'ArrowRight') rendition.next();
            });
            
            function goToLocation() {
                const pageNum = parseInt(gotoInput.value.trim(), 10);
                gotoInput.value = '';
                const totalContentPages = book.locations.total - 1;

                if (!isNaN(pageNum) && pageNum > 0 && book.locations && pageNum <= totalContentPages) {
                    const cfi = book.locations.cfiFromLocation(pageNum);
                    navigateTo(cfi);
                }
            }

            gotoBtn.addEventListener('click', goToLocation);
            gotoInput.addEventListener('keypress', (e) => e.key === 'Enter' && goToLocation());

            sidebarBtn.addEventListener('click', () => mainSidebar.classList.remove('translate-x-full'));
            closeSidebarBtn.addEventListener('click', () => mainSidebar.classList.add('translate-x-full'));
            settingsBtn.addEventListener('click', () => settingsModal.classList.remove('hidden'));
            closeSettingsBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));
            searchBtn.addEventListener('click', () => searchModal.classList.remove('hidden'));
            closeSearchBtn.addEventListener('click', () => searchModal.classList.add('hidden'));

            fontSizeSlider.addEventListener('input', (e) => { userSettings.fontSize = parseInt(e.target.value); applySettings(); });
            fontSizeSlider.addEventListener('change', saveSettings);
            fontFamilySelect.addEventListener('change', (e) => { userSettings.fontFamily = e.target.value; applySettings(); saveSettings(); });
            
            bgColorInput.addEventListener('input', () => setReaderBgColor(bgColorInput.value, false));
            bgColorInput.addEventListener('change', () => setReaderBgColor(bgColorInput.value, true));
            
            doSearchBtn.addEventListener('click', doSearch);
            searchInput.addEventListener('keypress', (e) => e.key === 'Enter' && doSearch());
            
            rendition.on("rendered", (section) => {
                loader.style.display = 'none';
            });

            rendition.on("relocated", (location) => {
                const totalContentPages = book.locations.total - 1;
                const currentLocation = book.locations.locationFromCfi(location.start.cfi);

                if (currentLocation > 0) {
                    const currentPage = currentLocation;
                    const percentage = totalContentPages > 0 ? Math.round((currentPage / totalContentPages) * 100) : 100;
                    progressSpan.textContent = `Trang ${currentPage} / ${totalContentPages} (${percentage}%)`;
                } else {
                    progressSpan.textContent = 'Bìa sách';
                }
                
                if (!isProgrammaticNavigation) {
                    localStorage.setItem(`kavita-progress-${book.key()}`, location.start.cfi);
                }
            });
        }
        
        function saveSettings() {
            apiCall(`/save_settings/${bookId}`, 'POST', { settings: userSettings });
        }
        
        function getTextColorForBg(hexcolor){
            hexcolor = hexcolor.replace("#", "");
            const r = parseInt(hexcolor.substr(0,2),16);
            const g = parseInt(hexcolor.substr(2,2),16);
            const b = parseInt(hexcolor.substr(4,2),16);
            const yiq = ((r*299)+(g*587)+(b*114))/1000;
            return (yiq >= 128) ? '#000000' : '#FFFFFF';
        }

        function setReaderBgColor(color, shouldSave) {
            const textColor = getTextColorForBg(color);
            rendition.themes.override("background-color", color, true);
            rendition.themes.override("color", textColor, true);
            userSettings.bgColor = color;
            if (shouldSave) {
                saveSettings();
            }
        }

        function applySettings() {
            rendition.themes.fontSize(userSettings.fontSize + '%');
            fontSizeSlider.value = userSettings.fontSize;
            rendition.themes.font(userSettings.fontFamily);
            fontFamilySelect.value = userSettings.fontFamily;
            
            const color = userSettings.bgColor || '#111827';
            bgColorInput.value = color;
            setReaderBgColor(color, false);
        }

        async function setupToc() {
            const toc = await book.loaded.navigation;
            buildToc(toc.toc, tocPanel);
        }

        function buildToc(tocItems, container) {
            const ul = document.createElement('ul');
            tocItems.forEach(item => {
                const li = document.createElement('li');
                const a = document.createElement('a');
                a.textContent = item.label.trim();
                a.href = item.href;
                a.className = 'sidebar-content-item text-black dark:text-white';
                a.onclick = (e) => {
                    e.preventDefault();
                    navigateTo(item.href);
                    mainSidebar.classList.add('translate-x-full');
                };
                li.appendChild(a);
                if (item.subitems && item.subitems.length > 0) {
                    const subUl = buildToc(item.subitems, li);
                    subUl.style.paddingLeft = '1rem';
                }
                ul.appendChild(li);
            });
            container.appendChild(ul);
            return ul;
        }

        async function doSearch() {
            const query = searchInput.value.trim();
            if (!query) return;
            searchResultsContainer.innerHTML = '<p class="text-center"><i class="fas fa-spinner fa-spin"></i> Đang tìm...</p>';
            const results = await Promise.all(book.spine.spineItems.map(item => item.load(book.load.bind(book)).then(item.find.bind(item, query)).finally(item.unload.bind(item))));
            const searchResults = [].concat.apply([], results);
            searchResultsContainer.innerHTML = '';
            if(searchResults.length > 0) {
                searchResults.forEach(result => {
                    const itemDiv = document.createElement('div');
                    itemDiv.className = 'p-3 border-b border-gray-700 cursor-pointer hover:bg-gray-700';
                    itemDiv.innerHTML = `<p class="truncate">${result.excerpt}</p>`;
                    itemDiv.onclick = () => { 
                        navigateTo(result.cfi); 
                        searchModal.classList.add('hidden'); 
                    };
                    searchResultsContainer.appendChild(itemDiv);
                });
            } else {
                searchResultsContainer.innerHTML = '<p class="text-gray-500 text-center">Không tìm thấy kết quả.</p>';
            }
        };

        main();
    </script>
</body>
</html>
"""

SETTINGS_TEMPLATE = """
<div x-data="settingsManager()" class="bg-white dark:bg-gray-800 rounded-xl shadow-md p-8 max-w-3xl mx-auto">
    <h2 class="text-2xl font-bold mb-6 text-gray-900 dark:text-white">Cài đặt Hệ thống</h2>
    <form @submit.prevent="saveSettings">
        <!-- Tên Thư viện -->
        <div class="mb-6">
            <label for="library_name" class="block text-gray-600 dark:text-gray-400 font-bold mb-2">Tên Thư viện</label>
            <input name="library_name" id="library_name" x-model="libraryName" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500">
            <p class="text-gray-500 text-sm mt-2">Tên sẽ hiển thị ở đầu trang.</p>
        </div>

        <!-- Cai dat Thu muc Du lieu -->
        <div class="mb-6">
            <label for="data_path" class="block text-gray-600 dark:text-gray-400 font-bold mb-2">Đường dẫn Thư mục Dữ liệu</label>
            <div class="flex">
                <input name="data_path" id="data_path" x-model="dataPath" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-l-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500">
                <button @click.prevent="openBrowser" type="button" class="px-4 py-2 bg-gray-500 hover:bg-gray-600 text-white rounded-r-lg">
                    <i class="fas fa-folder-open"></i>
                </button>
            </div>
            <p class="text-gray-500 text-sm mt-2">Nơi lưu trữ cơ sở dữ liệu, sách và ảnh bìa. <strong>Thay đổi yêu cầu khởi động lại ứng dụng để có hiệu lực.</strong></p>
        </div>

        <!-- Cai dat Giao dien -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
                <label for="theme" class="block text-gray-600 dark:text-gray-400 font-bold mb-2">Giao diện</label>
                <select name="theme" id="theme" x-model="theme" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500">
                    <option value="dark">Tối</option>
                    <option value="light">Sáng</option>
                </select>
            </div>
            <div>
                <label for="theme_color" class="block text-gray-600 dark:text-gray-400 font-bold mb-2">Màu chủ đề</label>
                <select name="theme_color" id="theme_color" x-model="themeColor" class="w-full px-3 py-2 bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg border border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-theme-500">
                    <option value="cyan">Cyan</option>
                    <option value="blue">Blue</option>
                    <option value="emerald">Emerald</option>
                    <option value="rose">Rose</option>
                    <option value="indigo">Indigo</option>
                    <option value="violet">Violet</option>
                    <option value="fuchsia">Fuchsia</option>
                    <option value="orange">Orange</option>
                </select>
            </div>
        </div>

        <button type="submit" class="w-full px-4 py-3 bg-theme-600 text-white font-bold rounded-lg hover:bg-theme-700 transition-colors">
            <i class="fas fa-save mr-2"></i> Lưu Cài đặt
        </button>
    </form>

    <!-- Modal Trinh duyet File -->
    <div x-show="isBrowserOpen" @click.away="isBrowserOpen = false" class="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4" x-cloak>
        <div class="bg-gray-800 rounded-lg p-4 max-w-2xl w-full h-3/4 flex flex-col">
            <h3 class="text-xl font-bold text-white mb-2" x-text="currentPath"></h3>
            <div class="flex-grow bg-gray-900 rounded-lg p-2 overflow-y-auto">
                <ul>
                    <!-- Nut Len thu muc cha -->
                    <li x-show="currentPath !== '{{ safe_root }}'">
                        <a href="#" @click.prevent="browse('..')" class="flex items-center p-2 text-gray-300 hover:bg-gray-700 rounded-md">
                            <i class="fas fa-arrow-up w-6 mr-2 text-yellow-400"></i> .. (Thư mục cha)
                        </a>
                    </li>
                    <!-- Danh sach thu muc -->
                    <template x-for="dir in directories" :key="dir">
                        <li>
                            <a href="#" @click.prevent="browse(dir)" class="flex items-center p-2 text-gray-300 hover:bg-gray-700 rounded-md">
                                <i class="fas fa-folder w-6 mr-2 text-cyan-400"></i>
                                <span x-text="dir"></span>
                            </a>
                        </li>
                    </template>
                </ul>
            </div>
            <div class="flex justify-end space-x-4 mt-4">
                <button @click="isBrowserOpen = false" type="button" class="px-4 py-2 bg-gray-600 rounded-lg hover:bg-gray-500">Hủy</button>
                <button @click="selectPath" type="button" class="px-4 py-2 bg-theme-600 text-white rounded-lg hover:bg-theme-700">Chọn Thư mục này</button>
            </div>
        </div>
    </div>
</div>

<script>
function settingsManager() {
    return {
        isBrowserOpen: false,
        libraryName: '{{ app_config.library_name }}',
        dataPath: '{{ app_config.data_path }}',
        currentPath: '{{ safe_root }}',
        directories: [],
        theme: localStorage.getItem('kavita_theme') || '{{ app_config.theme }}',
        themeColor: localStorage.getItem('kavita_theme_color') || '{{ app_config.theme_color }}',

        openBrowser() {
            this.isBrowserOpen = true;
            this.fetchDirectories(this.currentPath);
        },
        fetchDirectories(path) {
            fetch(`/api/browse?path=${encodeURIComponent(path)}`)
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        this.currentPath = data.path;
                        this.directories = data.directories.sort();
                    } else {
                        alert('Lỗi: ' + data.error);
                    }
                });
        },
        browse(dir) {
            let newPath = this.currentPath;
            if (dir === '..') {
                newPath = newPath.substring(0, newPath.lastIndexOf('/')) || '/';
                 if (newPath.length > 1 && newPath.endsWith('/')) {
                    newPath = newPath.slice(0, -1);
                }
            } else {
                newPath = this.currentPath === '/' ? `/${dir}` : `${this.currentPath}/${dir}`;
            }
            this.fetchDirectories(newPath);
        },
        selectPath() {
            this.dataPath = this.currentPath;
            this.isBrowserOpen = false;
        },
        saveSettings() {
            // Update localStorage immediately for instant UI feedback
            const oldTheme = localStorage.getItem('kavita_theme');
            const oldColor = localStorage.getItem('kavita_theme_color');

            localStorage.setItem('kavita_theme', this.theme);
            localStorage.setItem('kavita_theme_color', this.themeColor);

            // Create a form dynamically to POST data
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '{{ url_for("settings") }}';

            const nameInput = document.createElement('input');
            nameInput.type = 'hidden';
            nameInput.name = 'library_name';
            nameInput.value = this.libraryName;
            form.appendChild(nameInput);

            const dataPathInput = document.createElement('input');
            dataPathInput.type = 'hidden';
            dataPathInput.name = 'data_path';
            dataPathInput.value = this.dataPath;
            form.appendChild(dataPathInput);

            const themeInput = document.createElement('input');
            themeInput.type = 'hidden';
            themeInput.name = 'theme';
            themeInput.value = this.theme;
            form.appendChild(themeInput);

            const colorInput = document.createElement('input');
            colorInput.type = 'hidden';
            colorInput.name = 'theme_color';
            colorInput.value = this.themeColor;
            form.appendChild(colorInput);

            document.body.appendChild(form);
            form.submit();
            
            // Reload if theme settings changed
            if (oldTheme !== this.theme || oldColor !== this.themeColor) {
                 // The form submission will cause a page reload anyway
            }
        }
    }
}
</script>
"""


# -------------------- ROUTES (Cac duong dan cua ung dung) --------------------

@app.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    query_str = request.args.get('q', '').strip()
    user_id = session.get('user_id')
    is_admin = session.get('is_admin')

    if is_admin:
        base_books_query = Book.query
    else:
        base_books_query = Book.query.filter_by(user_id=user_id)

    subquery = base_books_query.with_entities(db.func.min(Book.id).label("min_id")).group_by(Book.title, Book.author).subquery()
    books_query = Book.query.join(subquery, Book.id == subquery.c.min_id)

    random_books = []
    if not query_str and page == 1:
        random_books = books_query.order_by(func.random()).limit(5).all()

    if query_str:
        unaccented_query = remove_diacritics(query_str)
        search_term = f"%{unaccented_query}%"
        books_query = books_query.filter(
            or_(
                db.func.unaccent(Book.title).like(search_term),
                and_(Book.author != None, db.func.unaccent(Book.author).like(search_term)),
                and_(Book.tags != None, db.func.unaccent(Book.tags).like(search_term)),
                and_(Book.series != None, db.func.unaccent(Book.series).like(search_term))
            )
        )
        relevance = case(
            (db.func.unaccent(Book.title).like(unaccented_query), 1),
            (db.func.unaccent(Book.title).like(f"{unaccented_query}%"), 2),
            (and_(Book.author != None, db.func.unaccent(Book.author).like(unaccented_query)), 3),
            else_=10
        ).label("relevance")
        pagination = books_query.order_by(relevance, Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)
    else:
        pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)
    
    bookmarked_set = set()
    favorited_set = set()
    if session.get('logged_in'):
        bm_user_id = session.get('user_id')
        bookmarked_books_query = db.session.query(Book.title, Book.author).join(BookMark, BookMark.book_id == Book.id).filter(BookMark.user_id == bm_user_id).distinct()
        bookmarked_set = {(b.title, b.author) for b in bookmarked_books_query.all()}
        
        favorited_books_query = db.session.query(Book.title, Book.author).join(Favorite, Favorite.book_id == Book.id).filter(Favorite.user_id == bm_user_id).distinct()
        favorited_set = {(b.title, b.author) for b in favorited_books_query.all()}

    
    for book in pagination.items:
        book.is_bookmarked = (book.title, book.author) in bookmarked_set
        book.is_favorited = (book.title, book.author) in favorited_set
        if is_admin:
            book.owner_username = book.user.username
            
    for book in random_books:
        book.is_bookmarked = (book.title, book.author) in bookmarked_set
        book.is_favorited = (book.title, book.author) in favorited_set

    index_content = render_template_string(INDEX_TEMPLATE, pagination=pagination, query=query_str, page_title="Thư viện", random_books=random_books, is_admin=is_admin)
    return render_template_string(LAYOUT_TEMPLATE, content=index_content, query=query_str)

@app.route('/library/<int:user_id>')
@login_required
def view_user_library(user_id):
    if not session.get('is_admin'):
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    page = request.args.get('page', 1, type=int)
    query_str = request.args.get('q', '').strip()

    base_books_query = Book.query.filter_by(user_id=user_id)
    subquery = base_books_query.with_entities(db.func.min(Book.id).label("min_id")).group_by(Book.title, Book.author).subquery()
    books_query = Book.query.join(subquery, Book.id == subquery.c.min_id)

    if query_str:
        unaccented_query = remove_diacritics(query_str)
        search_term = f"%{unaccented_query}%"
        books_query = books_query.filter(
            or_(
                db.func.unaccent(Book.title).like(search_term),
                and_(Book.author != None, db.func.unaccent(Book.author).like(search_term))
            )
        )
        pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)
    else:
        pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)
    
    page_title = f"Thư viện của: {user.username}"
    index_content = render_template_string(INDEX_TEMPLATE, pagination=pagination, query=query_str, page_title=page_title, is_admin=False, random_books=None)
    return render_template_string(LAYOUT_TEMPLATE, content=index_content, query=query_str)

@app.route('/favorites')
@login_required
def favorites():
    user_id = session.get('user_id')
    page = request.args.get('page', 1, type=int)
    
    if session.get('username') == GUEST_USERNAME:
        permissions = GuestPermission.query.first()
        if not permissions or not permissions.can_favorite:
            flash('Tài khoản khách không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('index'))

    favorited_book_ids = db.session.query(Favorite.book_id).filter_by(user_id=user_id).subquery()
    
    subquery = db.session.query(db.func.min(Book.id).label("min_id")) \
        .filter(Book.id.in_(favorited_book_ids)) \
        .group_by(Book.title, Book.author).subquery()

    books_query = Book.query.join(subquery, Book.id == subquery.c.min_id)
    pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)

    for book in pagination.items:
        book.is_favorited = True
        book.is_bookmarked = BookMark.query.filter_by(user_id=user_id, book_id=book.id).first() is not None

    index_content = render_template_string(INDEX_TEMPLATE, pagination=pagination, query='', page_title="Sách Yêu Thích", is_admin=session.get('is_admin'))
    return render_template_string(LAYOUT_TEMPLATE, content=index_content, query='')


@app.route('/bookmarks')
@login_required
def bookmarks():
    user_id = session.get('user_id')
    page = request.args.get('page', 1, type=int)
    
    if session.get('username') == GUEST_USERNAME:
        permissions = GuestPermission.query.first()
        if not permissions or not permissions.can_bookmark:
            flash('Tài khoản khách không có quyền truy cập trang này.', 'danger')
            return redirect(url_for('index'))

    bookmarked_book_ids = db.session.query(BookMark.book_id).filter_by(user_id=user_id).subquery()
    
    subquery = db.session.query(db.func.min(Book.id).label("min_id")) \
        .filter(Book.id.in_(bookmarked_book_ids)) \
        .group_by(Book.title, Book.author).subquery()

    books_query = Book.query.join(subquery, Book.id == subquery.c.min_id)
    pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)

    for book in pagination.items:
        book.is_bookmarked = True
        book.is_favorited = Favorite.query.filter_by(user_id=user_id, book_id=book.id).first() is not None


    index_content = render_template_string(INDEX_TEMPLATE, pagination=pagination, query='', page_title="Sách Đã Đánh Dấu", is_admin=session.get('is_admin'))
    return render_template_string(LAYOUT_TEMPLATE, content=index_content, query='')

@app.route('/lists/create', methods=['POST'])
@login_required
def create_list():
    data = request.get_json()
    list_name = data.get('name', '').strip()

    if not list_name:
        return jsonify(success=False, message="Tên kệ sách không được để trống.")
    
    user_id = session.get('user_id')
    existing_list = BookList.query.filter_by(user_id=user_id, name=list_name).first()
    if existing_list:
        return jsonify(success=False, message="Kệ sách với tên này đã tồn tại.")

    new_list = BookList(name=list_name, user_id=user_id)
    db.session.add(new_list)
    db.session.commit()
    return jsonify(success=True, message="Đã tạo kệ sách mới.", list={'id': new_list.id, 'name': new_list.name})

@app.route('/lists/<int:list_id>')
@login_required
def view_list(list_id):
    page = request.args.get('page', 1, type=int)
    user_id = session.get('user_id')
    book_list = BookList.query.filter_by(id=list_id, user_id=user_id).first_or_404()

    unique_books_in_list_subquery = book_list.books.with_entities(func.min(Book.id).label('min_id')).group_by(Book.title, Book.author).subquery()
    books_query = Book.query.join(unique_books_in_list_subquery, Book.id == unique_books_in_list_subquery.c.min_id)
    pagination = books_query.order_by(Book.title).paginate(page=page, per_page=BOOKS_PER_PAGE, error_out=False)
    
    bookmarked_set = set()
    favorited_set = set()
    if session.get('logged_in'):
        bm_user_id = session.get('user_id')
        bookmarked_books_query = db.session.query(Book.title, Book.author).join(BookMark, BookMark.book_id == Book.id).filter(BookMark.user_id == bm_user_id).distinct()
        bookmarked_set = {(b.title, b.author) for b in bookmarked_books_query.all()}
        
        favorited_books_query = db.session.query(Book.title, Book.author).join(Favorite, Favorite.book_id == Book.id).filter(Favorite.user_id == bm_user_id).distinct()
        favorited_set = {(b.title, b.author) for b in favorited_books_query.all()}

    for book in pagination.items:
        book.is_bookmarked = (book.title, book.author) in bookmarked_set
        book.is_favorited = (book.title, book.author) in favorited_set

    index_content = render_template_string(INDEX_TEMPLATE, pagination=pagination, query='', page_title=f"Kệ sách: {book_list.name}", is_admin=session.get('is_admin'))
    return render_template_string(LAYOUT_TEMPLATE, content=index_content, query='')

@app.route('/api/book/<int:book_id>/lists', methods=['GET'])
@login_required
def get_book_lists(book_id):
    book_rep = check_book_permission(book_id)
    if not book_rep:
        return jsonify(success=False, message="Không có quyền truy cập.")

    user_id = session.get('user_id')
    all_user_lists = BookList.query.filter_by(user_id=user_id).order_by(BookList.name).all()
    all_formats = Book.query.filter_by(title=book_rep.title, author=book_rep.author, user_id=book_rep.user_id).all()
    all_format_ids = {b.id for b in all_formats}

    result = []
    for lst in all_user_lists:
        count = db.session.query(book_list_association).filter(
            book_list_association.c.book_list_id == lst.id,
            book_list_association.c.book_id.in_(all_format_ids)
        ).count()
        result.append({'id': lst.id, 'name': lst.name, 'has_book': count > 0})
    
    return jsonify(success=True, lists=result)

@app.route('/api/lists/toggle_book', methods=['POST'])
@login_required
def toggle_book_in_list():
    data = request.get_json()
    book_id, list_id, action = data.get('book_id'), data.get('list_id'), data.get('action')
    user_id = session.get('user_id')
    book = check_book_permission(book_id)
    if not book: return jsonify(success=False, message="Không có quyền truy cập sách này.")
    book_list = BookList.query.filter_by(id=list_id, user_id=user_id).first()
    if not book_list: return jsonify(success=False, message="Không tìm thấy kệ sách.")

    all_formats = Book.query.filter_by(title=book.title, author=book.author, user_id=book.user_id).all()
    
    if action == 'add':
        for b in all_formats:
            if b not in book_list.books: book_list.books.append(b)
        message = "Đã thêm sách vào kệ."
    elif action == 'remove':
        for b in all_formats:
            if b in book_list.books: book_list.books.remove(b)
        message = "Đã xóa sách khỏi kệ."
    else:
        return jsonify(success=False, message="Hành động không hợp lệ.")

    db.session.commit()
    return jsonify(success=True, message=message)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        
        if user and ((user.password == password) or (user.username == GUEST_USERNAME and not password)):
            session['logged_in'] = True
            session['is_admin'] = user.is_admin
            session['username'] = user.username
            session['user_id'] = user.id
            flash('Đăng nhập thành công!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
    return render_template_string(LOGIN_TEMPLATE, GUEST_USERNAME=GUEST_USERNAME, app_config=load_config())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('Tên đăng nhập và mật khẩu không được để trống.', 'danger')
            return redirect(url_for('register'))
        if username in [ADMIN_USERNAME, GUEST_USERNAME] or User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return redirect(url_for('register'))

        new_user = User(username=username, password=password, is_admin=False)
        db.session.add(new_user)
        db.session.commit()
        flash('Đăng ký tài khoản thành công! Vui lòng đăng nhập.', 'success')
        return redirect(url_for('login'))

    return render_template_string(REGISTER_TEMPLATE, app_config=load_config())

@app.route('/logout')
def logout():
    session.clear()
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('login'))

def parse_opf(opf_content):
    metadata = {}
    try:
        root = ET.fromstring(opf_content)
        ns = {'dc': 'http://purl.org/dc/elements/1.1/', 'opf': 'http://www.idpf.org/2007/opf'}
        for key, path in [('title', './/dc:title'), ('author', './/dc:creator'), ('description', './/dc:description'), ('publisher', './/dc:publisher'), ('pubdate', './/dc:date'), ('language', './/dc:language')]:
            tag = root.find(path, ns)
            if tag is not None and tag.text: metadata[key] = tag.text
        subject_tags = root.findall('.//dc:subject', ns)
        if subject_tags: metadata['tags'] = ", ".join([tag.text for tag in subject_tags if tag.text])
        for meta_tag in root.findall('.//opf:meta', ns):
            if meta_tag.get('name') == 'calibre:series': metadata['series'] = meta_tag.get('content')
            elif meta_tag.get('name') == 'calibre:series_index': 
                try:
                    metadata['series_index'] = int(float(meta_tag.get('content')))
                except (ValueError, TypeError):
                    metadata['series_index'] = 1
    except Exception: pass
    return metadata

def extract_metadata(filepath):
    default_metadata = {
        'title': os.path.splitext(os.path.basename(filepath))[0], 
        'author': "Chưa rõ", 
        'format': os.path.splitext(filepath)[1][1:].lower(),
        'language': 'Tiếng Việt'
    }
    try:
        result = subprocess.run(["ebook-meta", "--to-opf", filepath], capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
        default_metadata.update(parse_opf(result.stdout))
    except Exception as e:
        print(f"Cảnh báo: Không thể trích xuất metadata cho {os.path.basename(filepath)}. Lỗi: {e}.")
    return default_metadata

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if session.get('username') == GUEST_USERNAME:
        permissions = GuestPermission.query.first()
        if not permissions or not permissions.can_upload_books:
            flash('Tài khoản khách không có quyền tải lên.', 'danger')
            return redirect(url_for('index'))

    files = request.files.getlist('files[]')
    if not files or files[0].filename == '':
        flash('Không có file nào được chọn.', 'danger')
        return redirect(request.url)

    user_id = session.get('user_id')
    user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    os.makedirs(user_upload_folder, exist_ok=True)
    
    newly_added_books = []
    warning_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(user_upload_folder, filename)
            file.save(filepath)
            metadata = extract_metadata(filepath)
            
            existing_book = Book.query.filter_by(title=metadata.get('title'), author=metadata.get('author'), format=metadata.get('format'), user_id=user_id).first()
            if existing_book:
                warning_count += 1
                os.remove(filepath)
                continue

            new_book = Book(filename=filename, user_id=user_id, **metadata)
            db.session.add(new_book)
            newly_added_books.append(new_book)
    
    db.session.commit() # Commit de sach co ID

    success_count = 0
    for book in newly_added_books:
        generate_and_save_cover(book)
        success_count +=1
    
    if success_count > 0: flash(f'{success_count} sách tải lên thành công.', 'success')
    if warning_count > 0: flash(f'{warning_count} sách đã tồn tại và được bỏ qua.', 'warning')
    return redirect(url_for('index'))

@app.route('/cover/<int:book_id>')
def cover(book_id):
    book = Book.query.get_or_404(book_id)
    cover_path = get_cover_path(book)

    if os.path.exists(cover_path):
        return send_file(cover_path, mimetype='image/jpeg')

    if generate_and_save_cover(book):
        return send_file(cover_path, mimetype='image/jpeg')
    
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'default_cover.jpg'), mimetype='image/jpeg')


@app.route('/cover/original/<int:book_id>')
@login_required
def cover_original(book_id):
    book = check_book_permission(book_id)
    if not book:
        return "Không có quyền", 403

    user_book_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(book.user_id))
    book_filepath = os.path.join(user_book_folder, book.filename)

    if not os.path.exists(book_filepath):
        return "File sách không tồn tại", 404

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_cover:
            temp_cover_path = tmp_cover.name
        
        subprocess.run(
            ["ebook-meta", book_filepath, "--get-cover", temp_cover_path],
            check=True, capture_output=True, timeout=30
        )
        if os.path.exists(temp_cover_path) and os.path.getsize(temp_cover_path) > 0:
            return send_file(temp_cover_path, mimetype='image/jpeg')
        else:
            return redirect(url_for('static', filename='default_cover.jpg'))
    except Exception as e:
        print(f"Lỗi khi trích xuất ảnh bìa gốc cho book ID {book.id}: {e}")
        return redirect(url_for('static', filename='default_cover.jpg'))

@app.route('/read/<int:book_id>')
@login_required
def read(book_id):
    book = check_book_permission(book_id)
    if not book:
        flash('Bạn không có quyền đọc sách này.', 'danger')
        return redirect(url_for('index'))
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], str(book.user_id), book.filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "File không tồn tại", 404

@app.route('/delete_format/<int:book_id>', methods=['POST'])
@login_required
def delete_format(book_id):
    book_to_delete = check_book_permission(book_id)
    if not book_to_delete:
        flash('Bạn không có quyền xóa định dạng sách này.', 'danger')
        return redirect(url_for('index'))

    # Store info before deleting
    original_title = book_to_delete.title
    original_author = book_to_delete.author
    user_id = book_to_delete.user_id

    # Delete the file and cover
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    try:
        os.remove(os.path.join(user_folder, book_to_delete.filename))
        cover_path = get_cover_path(book_to_delete)
        if os.path.exists(cover_path):
            os.remove(cover_path)
    except OSError as e:
        print(f"Lỗi khi xóa file cho book ID {book_id}: {e}")

    # Delete from DB
    db.session.delete(book_to_delete)
    db.session.commit()

    flash(f'Đã xóa định dạng {book_to_delete.format.upper()}.', 'success')

    # Check for remaining formats
    remaining_book = Book.query.filter_by(
        title=original_title,
        author=original_author,
        user_id=user_id
    ).first()

    if remaining_book:
        return redirect(url_for('book_detail', book_id=remaining_book.id))
    else:
        return redirect(url_for('index'))


@app.route('/serve_book_file/<int:book_id>')
@login_required
def serve_book_file(book_id):
    book = check_book_permission(book_id)
    if not book: return "Unauthorized", 401
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], str(book.user_id), book.filename)
    if os.path.exists(filepath): return send_file(filepath)
    return "File not found", 404

@app.route('/read_online/<int:book_id>')
@login_required
def read_online(book_id):
    book = check_book_permission(book_id)
    if not book:
        flash('Bạn không có quyền đọc sách này.', 'danger')
        return redirect(url_for('index'))
    if book.format != 'epub':
        flash('Đọc trực tuyến chỉ hỗ trợ file EPUB.', 'danger')
        return redirect(url_for('book_detail', book_id=book.id))
    
    history_entry = ReadingHistory.query.filter_by(user_id=session.get('user_id'), book_id=book_id).first()
    settings_json = history_entry.settings if history_entry else '{}'
    return render_template_string(EPUB_READER_TEMPLATE, book=book, settings_json=settings_json)

@app.route('/save_settings/<int:book_id>', methods=['POST'])
@login_required
def save_settings(book_id):
    book = check_book_permission(book_id)
    if not book: return jsonify(success=False, message="Không có quyền.")
    user_id = session.get('user_id')
    settings_data = request.get_json()
    history_entry = ReadingHistory.query.filter_by(user_id=user_id, book_id=book_id).first()
    if not history_entry:
        history_entry = ReadingHistory(user_id=user_id, book_id=book_id)
        db.session.add(history_entry)
    history_entry.settings = json.dumps(settings_data['settings'])
    db.session.commit()
    return jsonify(success=True)

@app.route('/book/<int:book_id>')
@login_required
def book_detail(book_id):
    book = check_book_permission(book_id)
    if not book:
        flash('Bạn không có quyền truy cập sách này.', 'danger')
        return redirect(url_for('index'))
    
    all_formats = Book.query.filter_by(title=book.title, author=book.author, user_id=book.user_id).order_by(Book.format).all()
    epub_book = next((b for b in all_formats if b.format == 'epub'), None)
    
    user_id = session.get('user_id')
    format_ids = [b.id for b in all_formats]
    is_bookmarked = BookMark.query.filter(BookMark.user_id==user_id, BookMark.book_id.in_(format_ids)).first() is not None
    is_favorited = Favorite.query.filter(Favorite.user_id==user_id, Favorite.book_id.in_(format_ids)).first() is not None

    related_books = Book.query.filter(Book.id != book.id, Book.user_id == book.user_id, or_(Book.author == book.author, Book.series == book.series)).limit(6).all()
    
    detail_content = render_template_string(BOOK_DETAIL_TEMPLATE, book=book, all_formats=all_formats, epub_book=epub_book, is_bookmarked=is_bookmarked, is_favorited=is_favorited, related_books=related_books)
    return render_template_string(LAYOUT_TEMPLATE, content=detail_content, query='')

@app.route('/edit/<int:book_id>', methods=['GET', 'POST'])
@login_required
def edit(book_id):
    book_rep = check_book_permission(book_id)
    if not book_rep:
        flash('Bạn không có quyền sửa sách này.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        form_data = request.form.to_dict()
        original_title = book_rep.title
        original_author = book_rep.author
        
        # --- Validation for Series Index ---
        form_series = form_data.get('series', '').strip()
        form_series_index_str = form_data.get('series_index')

        if form_series and form_series_index_str:
            try:
                form_series_index = int(form_series_index_str)
                books_to_update_ids = [b.id for b in Book.query.filter_by(title=original_title, author=original_author, user_id=book_rep.user_id).all()]
                
                existing_book_in_series = Book.query.filter(
                    Book.user_id == book_rep.user_id,
                    Book.series == form_series,
                    Book.series_index == form_series_index,
                    not_(Book.id.in_(books_to_update_ids))
                ).first()

                if existing_book_in_series:
                    flash(f'Tập số {form_series_index} đã tồn tại trong bộ truyện "{form_series}". Vui lòng chọn số khác.', 'danger')
                    # Populate book object with form data to avoid losing user's changes
                    for key, value in form_data.items():
                        if hasattr(book_rep, key):
                            setattr(book_rep, key, value)
                    edit_content = render_template_string(EDIT_TEMPLATE, book=book_rep)
                    return render_template_string(LAYOUT_TEMPLATE, content=edit_content, query='')

            except (ValueError, TypeError):
                flash('Tập số không hợp lệ.', 'danger')
                return redirect(url_for('edit', book_id=book_id))
        # --- End Validation ---

        books_to_update = Book.query.filter_by(title=original_title, author=original_author, user_id=book_rep.user_id).all()

        for book in books_to_update:
            for key, value in form_data.items():
                if hasattr(book, key) and key != 'cover_image':
                    # Handle integer conversion for series_index
                    if key == 'series_index' and value:
                        try:
                            setattr(book, key, int(value))
                        except (ValueError, TypeError):
                            setattr(book, key, 1)
                    else:
                        setattr(book, key, value)
        
        db.session.commit()

        cover_file = request.files.get('cover_image')
        if cover_file and cover_file.filename != '':
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(cover_file.filename)[1]) as tmp_upload:
                cover_file.save(tmp_upload)
                tmp_upload_path = tmp_upload.name

            try:
                with Image.open(tmp_upload_path) as img:
                    if img.height > COVER_MAX_HEIGHT:
                        ratio = COVER_MAX_HEIGHT / img.height
                        new_width = int(img.width * ratio)
                        img = img.resize((new_width, COVER_MAX_HEIGHT), Image.Resampling.LANCZOS)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    
                    for book in books_to_update:
                        final_cover_path = get_cover_path(book)
                        os.makedirs(os.path.dirname(final_cover_path), exist_ok=True)
                        img.save(final_cover_path, 'jpeg', quality=80, optimize=True)
                        book.has_cover = True
            except Exception as e:
                flash(f'Lỗi khi xử lý ảnh bìa mới: {e}', 'danger')
            finally:
                os.remove(tmp_upload_path)
        
        db.session.commit()
        flash('Cập nhật thông tin sách thành công!', 'success')
        return redirect(url_for('book_detail', book_id=book_rep.id))
    
    edit_content = render_template_string(EDIT_TEMPLATE, book=book_rep)
    return render_template_string(LAYOUT_TEMPLATE, content=edit_content, query='')

@app.route('/delete/<int:book_id>')
@login_required
def delete(book_id):
    book_rep = check_book_permission(book_id)
    if not book_rep:
        flash('Bạn không có quyền xóa sách này.', 'danger')
        return redirect(url_for('index'))
    
    books_to_delete = Book.query.filter_by(title=book_rep.title, author=book_rep.author, user_id=book_rep.user_id).all()
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(book_rep.user_id))
    
    for book in books_to_delete:
        try:
            os.remove(os.path.join(user_folder, book.filename))
            cover_path = get_cover_path(book)
            if os.path.exists(cover_path):
                os.remove(cover_path)
        except OSError: pass
        db.session.delete(book)
            
    db.session.commit()
    flash(f'Đã xóa sách "{book_rep.title}" và tất cả định dạng.', 'success')
    return redirect(url_for('index'))

@app.route('/toggle_favorite/<int:book_id>', methods=['POST'])
@login_required
def toggle_favorite(book_id):
    user_id = session.get('user_id')
    if session.get('username') == GUEST_USERNAME and not (GuestPermission.query.first() and GuestPermission.query.first().can_favorite):
        return jsonify(success=False, message="Tài khoản khách không được phép.")

    book_rep = check_book_permission(book_id)
    if not book_rep: return jsonify(success=False, message="Không có quyền.")

    all_format_ids = [b.id for b in Book.query.filter_by(title=book_rep.title, author=book_rep.author, user_id=book_rep.user_id).all()]
    favorite = Favorite.query.filter(Favorite.user_id == user_id, Favorite.book_id.in_(all_format_ids)).first()

    if not favorite:
        for bid in all_format_ids: db.session.add(Favorite(user_id=user_id, book_id=bid))
        status = "added"
    else:
        Favorite.query.filter(Favorite.user_id == user_id, Favorite.book_id.in_(all_format_ids)).delete()
        status = "removed"
    db.session.commit()
    return jsonify(success=True, status=status)

@app.route('/toggle_bookmark/<int:book_id>', methods=['POST'])
@login_required
def toggle_bookmark(book_id):
    user_id = session.get('user_id')
    if session.get('username') == GUEST_USERNAME and not (GuestPermission.query.first() and GuestPermission.query.first().can_bookmark):
        return jsonify(success=False, message="Tài khoản khách không được phép.")

    book_rep = check_book_permission(book_id)
    if not book_rep: return jsonify(success=False, message="Không có quyền.")

    all_format_ids = [b.id for b in Book.query.filter_by(title=book_rep.title, author=book_rep.author, user_id=book_rep.user_id).all()]
    bookmark = BookMark.query.filter(BookMark.user_id == user_id, BookMark.book_id.in_(all_format_ids)).first()

    if not bookmark:
        for bid in all_format_ids: db.session.add(BookMark(user_id=user_id, book_id=bid))
        status = "added"
    else:
        BookMark.query.filter(BookMark.user_id == user_id, BookMark.book_id.in_(all_format_ids)).delete()
        status = "removed"
    db.session.commit()
    return jsonify(success=True, status=status)

@app.route('/rate_book/<int:book_id>', methods=['POST'])
@login_required
def rate_book(book_id):
    book_rep = check_book_permission(book_id)
    if not book_rep: return jsonify(success=False, message="Không có quyền.")
    rating = request.get_json().get('rating')
    if rating is not None:
        books_to_rate = Book.query.filter_by(title=book_rep.title, author=book_rep.author, user_id=book_rep.user_id).all()
        for book in books_to_rate: book.rating = rating
        db.session.commit()
        return jsonify(success=True)
    return jsonify(success=False)

@app.route('/manage_users')
@login_required
def manage_users():
    if not session.get('is_admin'):
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    content = render_template_string(USER_MANAGEMENT_TEMPLATE, users=users)
    return render_template_string(LAYOUT_TEMPLATE, content=content, query='')

@app.route('/guest_permissions', methods=['GET', 'POST'])
@login_required
def guest_permissions():
    if not session.get('is_admin'):
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('index'))
    permissions = GuestPermission.query.first()
    if request.method == 'POST':
        permissions.can_favorite = 'can_favorite' in request.form
        permissions.can_bookmark = 'can_bookmark' in request.form
        permissions.can_rate = 'can_rate' in request.form
        permissions.can_upload_books = 'can_upload_books' in request.form
        db.session.commit()
        flash('Đã cập nhật quyền cho tài khoản khách.', 'success')
        return redirect(url_for('guest_permissions'))
    content = render_template_string(GUEST_PERMISSIONS_TEMPLATE, permissions=permissions)
    return render_template_string(LAYOUT_TEMPLATE, content=content, query='')

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if session.get('username') == GUEST_USERNAME:
        flash('Chức năng này không dành cho tài khoản khách.', 'danger')
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        if user.password != request.form.get('current_password'):
            flash('Mật khẩu hiện tại không đúng.', 'danger')
        elif request.form.get('new_password') != request.form.get('confirm_password'):
            flash('Mật khẩu mới không khớp.', 'danger')
        else:
            user.password = request.form.get('new_password')
            db.session.commit()
            flash('Đổi mật khẩu thành công.', 'success')
            return redirect(url_for('index'))
    content = render_template_string(CHANGE_PASSWORD_TEMPLATE)
    return render_template_string(LAYOUT_TEMPLATE, content=content, query='')

@app.route('/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not session.get('is_admin') or user_id == session.get('user_id'):
        flash('Hành động không được phép.', 'danger')
        return redirect(url_for('manage_users'))
    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f'Đã cập nhật quyền cho {user.username}.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not session.get('is_admin') or user_id == session.get('user_id') or User.query.get(user_id).username in [ADMIN_USERNAME, GUEST_USERNAME]:
        flash('Hành động không được phép.', 'danger')
        return redirect(url_for('manage_users'))
    user = User.query.get_or_404(user_id)
    shutil.rmtree(os.path.join(app.config['UPLOAD_FOLDER'], str(user_id)), ignore_errors=True)
    shutil.rmtree(os.path.join(app.config['COVER_FOLDER'], str(user_id)), ignore_errors=True)
    db.session.delete(user)
    db.session.commit()
    flash(f'Đã xóa người dùng {user.username}.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/import_calibre')
@login_required
def import_calibre():
    IMPORT_TEMPLATE = """
    <div class="bg-white dark:bg-gray-800 rounded-xl p-8 max-w-2xl mx-auto">
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Nhập từ Calibre</h2>
        <p class="text-gray-500 dark:text-gray-400 mb-6">Tải lên tệp .zip từ Calibre (được tạo bằng cách 'Lưu vào đĩa') để nhập hàng loạt.</p>
        <form method="POST" action="{{ url_for('process_calibre_import') }}" enctype="multipart/form-data">
            <label class="block w-full text-center px-4 py-10 bg-gray-50 dark:bg-gray-700 border-2 border-dashed border-gray-300 dark:border-gray-500 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/50 transition-colors">
                <i class="fas fa-file-archive text-4xl mb-2 text-gray-400"></i><br> 
                <span class="text-gray-800 dark:text-white font-semibold">Chọn tệp .zip</span>
                <input type="file" name="calibre_zip" class="hidden" accept=".zip" required onchange="this.form.submit()">
            </label>
        </form>
    </div>
    """
    content = render_template_string(IMPORT_TEMPLATE)
    return render_template_string(LAYOUT_TEMPLATE, content=content, query='')

@app.route('/process_calibre_import', methods=['POST'])
@login_required
def process_calibre_import():
    if session.get('username') == GUEST_USERNAME:
        permissions = GuestPermission.query.first()
        if not permissions or not permissions.can_upload_books:
            flash('Tài khoản khách không có quyền nhập sách.', 'danger')
            return redirect(url_for('import_calibre'))

    zip_file = request.files.get('calibre_zip')
    if not zip_file or zip_file.filename == '':
        flash('Không có file nào được chọn.', 'danger')
        return redirect(url_for('import_calibre'))
    if not zip_file.filename.lower().endswith('.zip'):
        flash('Chỉ chấp nhận file .zip.', 'danger')
        return redirect(url_for('import_calibre'))

    user_id = session.get('user_id')
    user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    os.makedirs(user_upload_folder, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp()
    
    newly_added_books_with_covers = []
    warning_count = 0
    error_count = 0
    
    try:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        for root, dirs, files in os.walk(temp_dir):
            if 'metadata.opf' in files:
                opf_path = os.path.join(root, 'metadata.opf')
                try:
                    with open(opf_path, 'r', encoding='utf-8', errors='ignore') as f:
                        opf_content = f.read()
                    
                    metadata = parse_opf(opf_content)
                    if not metadata.get('title'):
                        metadata['title'] = os.path.basename(root)

                    cover_source_path = os.path.join(root, 'cover.jpg') if 'cover.jpg' in files else None
                    
                    for file in files:
                        ext = file.rsplit('.', 1)[-1].lower()
                        if ext in ALLOWED_EXTENSIONS:
                            existing_book = Book.query.filter_by(
                                title=metadata.get('title'),
                                author=metadata.get('author'),
                                format=ext,
                                user_id=user_id
                            ).first()
                            if existing_book:
                                warning_count += 1
                                continue
                            
                            source_book_path = os.path.join(root, file)
                            safe_base = secure_filename(f"{metadata.get('author', 'Unknown')}_{metadata.get('title', 'Untitled')}_{datetime.now().timestamp()}")
                            new_filename = f"{safe_base}.{ext}"
                            dest_book_path = os.path.join(user_upload_folder, new_filename)
                            shutil.copy2(source_book_path, dest_book_path)

                            new_book_data = {
                                'filename': new_filename, 'title': metadata.get('title'), 'author': metadata.get('author', 'Chưa rõ'),
                                'format': ext, 'tags': metadata.get('tags'), 'description': metadata.get('description'),
                                'series': metadata.get('series'), 'series_index': metadata.get('series_index', 1),
                                'publisher': metadata.get('publisher'), 'pubdate': metadata.get('pubdate'),
                                'language': metadata.get('language') or 'Tiếng Việt', 'user_id': user_id, 'rating': 0,
                                'has_cover': False # Se cap nhat sau
                            }
                            new_book = Book(**{k: v for k, v in new_book_data.items() if v is not None})
                            db.session.add(new_book)
                            newly_added_books_with_covers.append((new_book, cover_source_path))

                except Exception as e:
                    error_count += 1
                    print(f"Lỗi khi xử lý sách từ Calibre import: {e} tại {root}")
        
        db.session.commit()

        success_count = 0
        for book, cover_src in newly_added_books_with_covers:
            if cover_src and os.path.exists(cover_src):
                final_cover_path = get_cover_path(book)
                os.makedirs(os.path.dirname(final_cover_path), exist_ok=True)
                with Image.open(cover_src) as img:
                    if img.height > COVER_MAX_HEIGHT:
                        ratio = COVER_MAX_HEIGHT / img.height
                        new_width = int(img.width * ratio)
                        img = img.resize((new_width, COVER_MAX_HEIGHT), Image.Resampling.LANCZOS)
                    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                    img.save(final_cover_path, 'jpeg', quality=80, optimize=True)
                    book.has_cover = True
            success_count += 1
        db.session.commit()

    except zipfile.BadZipFile:
        flash('File zip không hợp lệ hoặc bị hỏng.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Đã xảy ra lỗi không mong muốn: {e}', 'danger')
    finally:
        shutil.rmtree(temp_dir)

    flash_messages = []
    if success_count > 0: flash_messages.append(f"Nhập thành công {success_count} đầu sách.")
    if warning_count > 0: flash_messages.append(f"{warning_count} định dạng sách đã tồn tại và được bỏ qua.")
    if error_count > 0: flash_messages.append(f"Gặp lỗi khi xử lý {error_count} mục.")
    
    if flash_messages:
        flash(' '.join(flash_messages), 'success' if success_count > 0 and error_count == 0 else 'warning')
    else:
        flash("Không tìm thấy sách hợp lệ nào trong file zip.", "info")

    return redirect(url_for('index'))


@app.route('/convert/<int:book_id>', methods=['POST'])
@login_required
def convert_book(book_id):
    book = check_book_permission(book_id)
    if not book:
        flash('Bạn không có quyền thực hiện thao tác này.', 'danger')
        return redirect(url_for('index'))

    target_format = request.form.get('target_format')
    if not target_format:
        flash('Định dạng chuyển đổi không hợp lệ.', 'warning')
        return redirect(url_for('book_detail', book_id=book.id))

    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(book.user_id))
    source_path = os.path.join(user_folder, book.filename)
    output_filename = f"{os.path.splitext(book.filename)[0]}.{target_format}"
    output_path = os.path.join(user_folder, output_filename)

    try:
        subprocess.run(["ebook-convert", source_path, output_path], check=True, capture_output=True)
        new_book = Book(
            filename=output_filename, title=book.title, author=book.author,
            format=target_format, tags=book.tags, description=book.description,
            rating=book.rating, series=book.series, series_index=book.series_index,
            user_id=book.user_id
        )
        db.session.add(new_book)
        db.session.commit()

        # Tao anh bia cho dinh dang moi
        generate_and_save_cover(new_book)

        flash(f'Chuyển đổi sách thành công sang {target_format.upper()}!', 'success')
    except Exception as e:
        flash(f'Lỗi khi chuyển đổi sách: {e}', 'danger')
    
    return redirect(url_for('book_detail', book_id=book.id))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not session.get('is_admin'):
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('index'))
    
    current_config = load_config()

    if request.method == 'POST':
        # Cap nhat ten thu vien
        new_library_name = request.form.get('library_name', 'Thư Viện Sách').strip()
        if not new_library_name:
            new_library_name = 'Thư Viện Sách'

        # Cap nhat duong dan
        new_path = request.form.get('data_path', '').strip()
        if not new_path:
            flash('Đường dẫn dữ liệu không được để trống.', 'danger')
            return redirect(url_for('settings'))
        
        # Cap nhat giao dien
        new_theme = request.form.get('theme')
        new_theme_color = request.form.get('theme_color')

        # Luu cau hinh
        path_changed = os.path.abspath(new_path) != os.path.abspath(current_config['data_path'])
        
        current_config['library_name'] = new_library_name
        current_config['data_path'] = os.path.abspath(new_path)
        current_config['theme'] = new_theme
        current_config['theme_color'] = new_theme_color
        save_config(current_config)

        if path_changed:
            flash('Đã lưu cài đặt. Vui lòng KHỞI ĐỘNG LẠI ứng dụng để áp dụng thay đổi đường dẫn.', 'warning')
        else:
            flash('Đã lưu cài đặt. Tải lại trang để áp dụng thay đổi giao diện.', 'success')

        return redirect(url_for('settings'))

    content = render_template_string(SETTINGS_TEMPLATE, safe_root=SAFE_BROWSING_ROOT)
    return render_template_string(LAYOUT_TEMPLATE, content=content, query='')

@app.route('/api/browse')
@login_required
def browse_fs():
    if not session.get('is_admin'):
        return jsonify(success=False, error="Không có quyền truy cập"), 403

    req_path = request.args.get('path', SAFE_BROWSING_ROOT)
    
    # Bao mat: Chuan hoa duong dan va kiem tra xem no co nam trong thu muc an toan khong
    abs_path = os.path.abspath(req_path)
    if not abs_path.startswith(SAFE_BROWSING_ROOT):
        return jsonify(success=False, error="Truy cập bị từ chối"), 403

    if not os.path.isdir(abs_path):
        return jsonify(success=False, error="Đường dẫn không tồn tại"), 404

    try:
        dirs = [d for d in os.listdir(abs_path) if os.path.isdir(os.path.join(abs_path, d)) and not d.startswith('.')]
        return jsonify(success=True, path=abs_path, directories=dirs)
    except OSError as e:
        return jsonify(success=False, error=f"Không thể đọc thư mục: {e}"), 500

if __name__ == '__main__':
    # Doc cong tu file config khi khoi dong
    app_config = load_config()
    port = app_config.get('port', 5000)
    initialize_database()
    app.run(host='0.0.0.0', port=port, debug=True)
