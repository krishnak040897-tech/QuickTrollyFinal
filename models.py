import sqlite3
import json
import os
import random
import string
import traceback
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from datetime import datetime

# --- Barcode library availability checks ---
BARCODE_LIB_AVAILABLE = False
PILLOW_AVAILABLE = False
SVGWRITER_AVAILABLE = False

try:
    import barcode
    from barcode.codex import Code128
    BARCODE_LIB_AVAILABLE = True
except ImportError:
    BARCODE_LIB_AVAILABLE = False

try:
    from barcode.writer import ImageWriter
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    try:
        from barcode.writer import SVGWriter
        SVGWRITER_AVAILABLE = True
    except ImportError:
        SVGWRITER_AVAILABLE = False

# Fallback: try SVG writer if Pillow missing
if not PILLOW_AVAILABLE and not SVGWRITER_AVAILABLE:
    try:
        from barcode.writer import SVGWriter
        SVGWRITER_AVAILABLE = True
    except ImportError:
        SVGWRITER_AVAILABLE = False


class Database:
    def __init__(self):
        self.database_path = Config.DATABASE
        self.conn = sqlite3.connect(self.database_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._migrate_db()
        self._init_admin()
        self._ensure_barcode_dir()

        # Status print for debugging
        if not BARCODE_LIB_AVAILABLE:
            print("⚠️  python-barcode NOT installed. Run: pip install python-barcode")
        if not PILLOW_AVAILABLE:
            print("⚠️  Pillow NOT installed. PNG barcodes unavailable. Run: pip install Pillow")
            if SVGWRITER_AVAILABLE:
                print("✅ SVG fallback writer available.")

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                cart TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                original_price REAL NOT NULL,
                price REAL NOT NULL,
                qr_code TEXT UNIQUE NOT NULL,
                image TEXT DEFAULT '',
                barcode_number TEXT UNIQUE,
                barcode_image TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                email TEXT,
                payment_id TEXT,
                products TEXT NOT NULL,
                total REAL NOT NULL,
                date TEXT NOT NULL,
                status TEXT DEFAULT 'Pending'
            )
        ''')
        self.conn.commit()

    def _migrate_db(self):
        try:
            self.cursor.execute("ALTER TABLE products ADD COLUMN original_price REAL DEFAULT 0.0")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def _ensure_barcode_dir(self):
        """Create barcode directory using absolute path relative to project root."""
        base_dir = os.path.abspath(os.path.dirname(__file__))
        barcode_dir = os.path.join(base_dir, 'static', 'barcodes')
        if not os.path.exists(barcode_dir):
            os.makedirs(barcode_dir, exist_ok=True)
        return barcode_dir

    def _generate_unique_barcode(self):
        while True:
            barcode_num = ''.join([str(random.randint(0, 9)) for _ in range(12)])
            self.cursor.execute('SELECT id FROM products WHERE barcode_number = ?', (barcode_num,))
            if not self.cursor.fetchone():
                return barcode_num

    def _generate_barcode_image(self, barcode_number, product_id):
        """
        Generate a barcode image (PNG preferred, SVG fallback) for the given number.
        Returns the web-accessible URL path, or None on failure.
        """
        if not BARCODE_LIB_AVAILABLE:
            print("❌ Barcode library not available. Install: pip install python-barcode Pillow")
            return None

        try:
            barcode_dir = self._ensure_barcode_dir()
            filename_base = f"barcode_{product_id}_{barcode_number}"

            # --- Try PNG first (requires Pillow) ---
            saved_filepath = None
            web_url = None
            extension = None

            if PILLOW_AVAILABLE:
                try:
                    code128 = Code128(barcode_number, writer=ImageWriter())
                    options = {
                        'module_width': 0.4,
                        'module_height': 20.0,
                        'quiet_zone': 6.5,
                        'font_size': 10,
                        'text_distance': 5.0,
                        'write_text': True,
                    }
                    full_save_path = os.path.join(barcode_dir, filename_base)
                    saved_filepath = code128.save(full_save_path, options=options)
                    extension = '.png'
                except Exception as png_err:
                    print(f"⚠️  PNG barcode generation failed: {png_err}")
                    traceback.print_exc()
                    saved_filepath = None

            # --- Fallback to SVG if PNG failed or Pillow missing ---
            if not saved_filepath and SVGWRITER_AVAILABLE:
                try:
                    from barcode.writer import SVGWriter
                    code128 = Code128(barcode_number, writer=SVGWriter())
                    full_save_path = os.path.join(barcode_dir, filename_base)
                    saved_filepath = code128.save(full_save_path)
                    extension = '.svg'
                except Exception as svg_err:
                    print(f"❌ SVG barcode generation failed: {svg_err}")
                    traceback.print_exc()
                    saved_filepath = None

            if not saved_filepath:
                print("❌ All barcode generation methods failed.")
                return None

            # Verify file exists on disk
            if not os.path.exists(saved_filepath):
                print(f"❌ Saved barcode file does not exist: {saved_filepath}")
                return None

            web_url = f"/static/barcodes/{filename_base}{extension}"
            print(f"✅ Barcode generated: {web_url}")
            return web_url

        except Exception as e:
            print(f"❌ Unexpected barcode generation error: {e}")
            traceback.print_exc()
            return None

    def _init_admin(self):
        self.cursor.execute('SELECT id FROM users WHERE email = ?', ('admin',))
        if not self.cursor.fetchone():
            hashed_pw = generate_password_hash("admin123")
            self.cursor.execute('''
                INSERT INTO users (name, email, password, role, cart)
                VALUES (?, ?, ?, ?, ?)
            ''', ("Admin User", "admin", hashed_pw, "admin", "[]"))
            self.conn.commit()
            print("✅ Default Admin Created: admin / admin123")

    def _row_to_dict(self, row):
        if row is None:
            return None
        return dict(row)

    def create_user(self, name, email, password):
        self.cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        if self.cursor.fetchone():
            return False

        hashed_pw = generate_password_hash(password)
        try:
            self.cursor.execute('''
                INSERT INTO users (name, email, password, role, cart)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, email, hashed_pw, "user", "[]"))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def verify_user(self, email, password):
        self.cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = self.cursor.fetchone()
        if user and check_password_hash(user['password'], password):
            return self._row_to_dict(user)
        return None

    def get_user_cart(self, user_id):
        self.cursor.execute('SELECT cart FROM users WHERE id = ?', (user_id,))
        row = self.cursor.fetchone()
        if row:
            try:
                return json.loads(row['cart'])
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def update_user_cart(self, user_id, cart_data):
        cart_json = json.dumps(cart_data)
        self.cursor.execute('UPDATE users SET cart = ? WHERE id = ?', (cart_json, user_id))
        self.conn.commit()

    def add_item_to_cart(self, user_id, product):
        cart = self.get_user_cart(user_id)
        p_id = str(product.get('_id') or product.get('id'))
        existing = next((item for item in cart if (str(item.get('_id')) == p_id or str(item.get('id')) == p_id)), None)

        if existing:
            existing['qty'] = existing.get('qty', 0) + 1
        else:
            product['qty'] = 1
            if '_id' not in product:
                product['_id'] = p_id
            cart.append(product)

        self.update_user_cart(user_id, cart)
        return True

    def remove_item_from_cart(self, user_id, product_id):
        cart = self.get_user_cart(user_id)
        p_str = str(product_id)
        item_index = next((i for i, item in enumerate(cart) if (str(item.get('_id')) == p_str or str(item.get('id')) == p_str)), None)

        if item_index is not None:
            if cart[item_index].get('qty', 1) > 1:
                cart[item_index]['qty'] -= 1
            else:
                cart.pop(item_index)

        self.update_user_cart(user_id, cart)
        return True

    def clear_cart(self, user_id):
        self.cursor.execute('UPDATE users SET cart = ? WHERE id = ?', ("[]", user_id))
        self.conn.commit()

    def get_all_products(self):
        self.cursor.execute('SELECT * FROM products ORDER BY created_at DESC')
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products

    def get_product_by_qr(self, qr_code):
        self.cursor.execute('SELECT * FROM products WHERE qr_code = ?', (qr_code,))
        row = self.cursor.fetchone()
        if row:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def get_product_by_barcode(self, barcode_number):
        self.cursor.execute('SELECT * FROM products WHERE barcode_number = ?', (barcode_number,))
        row = self.cursor.fetchone()
        if row:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def get_product_by_id(self, product_id):
        self.cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        row = self.cursor.fetchone()
        if row:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def add_product(self, name, original_price, price, qr_code, image_url):
        barcode_number = self._generate_unique_barcode()
        self.cursor.execute('''
            INSERT INTO products (name, original_price, price, qr_code, image, barcode_number, barcode_image, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, float(original_price), float(price), qr_code, image_url, barcode_number, None, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()

        product_id = self.cursor.lastrowid
        barcode_image = self._generate_barcode_image(barcode_number, product_id)

        # Retry once if generation failed
        if not barcode_image:
            print("🔄 Retrying barcode generation...")
            barcode_image = self._generate_barcode_image(barcode_number, product_id)

        self.cursor.execute('UPDATE products SET barcode_image = ? WHERE id = ?', (barcode_image, product_id))
        self.conn.commit()
        return str(product_id)

    def update_product(self, product_id, name, original_price, price, qr_code, image_url):
        existing = self.get_product_by_id(product_id)
        if not existing:
            return

        barcode_number = existing.get('barcode_number')
        barcode_image = existing.get('barcode_image')

        if not barcode_number:
            barcode_number = self._generate_unique_barcode()
            barcode_image = self._generate_barcode_image(barcode_number, product_id)

        self.cursor.execute('''
            UPDATE products
            SET name = ?, original_price = ?, price = ?, qr_code = ?, image = ?, barcode_number = ?,
                barcode_image = ?, updated_at = ?
            WHERE id = ?
        ''', (name, float(original_price), float(price), qr_code, image_url, barcode_number, barcode_image,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), product_id))
        self.conn.commit()

    def delete_product(self, product_id):
        product = self.get_product_by_id(product_id)
        if product and product.get('barcode_image'):
            try:
                img_path = product['barcode_image'].lstrip('/')
                base_dir = os.path.abspath(os.path.dirname(__file__))
                full_path = os.path.join(base_dir, img_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print(f"Error deleting barcode image: {e}")

        self.cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def regenerate_barcode(self, product_id):
        product = self.get_product_by_id(product_id)
        if not product:
            return None

        if product.get('barcode_image'):
            try:
                img_path = product['barcode_image'].lstrip('/')
                base_dir = os.path.abspath(os.path.dirname(__file__))
                full_path = os.path.join(base_dir, img_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print(f"Error deleting old barcode: {e}")

        barcode_number = self._generate_unique_barcode()
        barcode_image = self._generate_barcode_image(barcode_number, product_id)

        if not barcode_image:
            print("🔄 Retrying barcode generation...")
            barcode_image = self._generate_barcode_image(barcode_number, product_id)

        self.cursor.execute('''
            UPDATE products
            SET barcode_number = ?, barcode_image = ?
            WHERE id = ?
        ''', (barcode_number, barcode_image, product_id))
        self.conn.commit()
        return {"barcode_number": barcode_number, "barcode_image": barcode_image}

    def create_order(self, customer_name, phone, address, products, total, email=None, payment_id=None):
        products_json = json.dumps(products)
        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.cursor.execute('''
            INSERT INTO orders (customer_name, phone, address, email, payment_id, products, total, date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (customer_name, phone, address, email, payment_id, products_json, total, order_date, "Pending"))
        self.conn.commit()
        return str(self.cursor.lastrowid)

    def get_order_by_id(self, order_id):
        self.cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        row = self.cursor.fetchone()
        if row:
            order = self._row_to_dict(row)
            order['_id'] = str(order['id'])
            try:
                order['products'] = json.loads(order['products'])
            except (json.JSONDecodeError, TypeError):
                order['products'] = []
            return order
        return None

    def get_all_orders(self):
        self.cursor.execute('SELECT * FROM orders ORDER BY date DESC')
        rows = self.cursor.fetchall()
        orders = []
        for row in rows:
            order = self._row_to_dict(row)
            order['_id'] = str(order['id'])
            try:
                order['products'] = json.loads(order['products'])
            except (json.JSONDecodeError, TypeError):
                order['products'] = []
            orders.append(order)
        return orders

    def update_order_status(self, order_id, status):
        self.cursor.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM products')
        total_products = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM orders')
        total_orders = self.cursor.fetchone()[0]
        return total_products, total_orders

    def get_user_count(self):
        self.cursor.execute('SELECT COUNT(*) FROM users')
        return self.cursor.fetchone()[0]

    def get_recent_products(self, limit=5):
        self.cursor.execute('SELECT * FROM products ORDER BY created_at DESC LIMIT ?', (limit,))
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products

    def search_products(self, search_term):
        search_pattern = f'%{search_term}%'
        self.cursor.execute('''
            SELECT * FROM products
            WHERE name LIKE ? OR qr_code LIKE ? OR barcode_number LIKE ?
            ORDER BY created_at DESC
        ''', (search_pattern, search_pattern, search_pattern))
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = self._row_to_dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products


db = Database()