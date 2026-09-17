import psycopg2
import psycopg2.extras
import json
import os
import random
import traceback
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from datetime import datetime
import cloudinary
import cloudinary.uploader

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

# --- Cloudinary Initialization ---
if Config.CLOUDINARY_CLOUD_NAME and Config.CLOUDINARY_API_KEY and Config.CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=Config.CLOUDINARY_CLOUD_NAME,
        api_key=Config.CLOUDINARY_API_KEY,
        api_secret=Config.CLOUDINARY_API_SECRET,
        secure=True
    )

class Database:
    def __init__(self):
        self.database_url = Config.DATABASE_URL
        self.conn = psycopg2.connect(self.database_url)
        self.conn.autocommit = True
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._create_tables()
        self._migrate_db()
        self._init_admin()

        if not BARCODE_LIB_AVAILABLE:
            print("⚠️  python-barcode NOT installed. Run: pip install python-barcode")
        if not PILLOW_AVAILABLE:
            print("⚠️  Pillow NOT installed. PNG barcodes unavailable. Run: pip install Pillow")
            if SVGWRITER_AVAILABLE:
                print("✅ SVG fallback writer available.")

    def _create_tables(self):
        # QuickTrolly-specific tables to avoid conflicts with other applications
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS qt_users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                cart TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS qt_products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                original_price REAL NOT NULL,
                price REAL NOT NULL,
                qr_code TEXT UNIQUE NOT NULL,
                image TEXT DEFAULT '',
                barcode_number TEXT UNIQUE,
                barcode_image TEXT DEFAULT NULL,
                barcode_public_id TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS qt_orders (
                id SERIAL PRIMARY KEY,
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

    def _migrate_db(self):
        try:
            self.cursor.execute("ALTER TABLE qt_products ADD COLUMN IF NOT EXISTS original_price REAL DEFAULT 0.0")
            self.cursor.execute("ALTER TABLE qt_products ADD COLUMN IF NOT EXISTS barcode_public_id TEXT DEFAULT NULL")
        except psycopg2.Error:
            pass

    def _upload_barcode_to_cloudinary(self, barcode_number, product_id):
        if not BARCODE_LIB_AVAILABLE:
            print("❌ Barcode library not available. Install: pip install python-barcode Pillow")
            return None, None

        local_filepath = None
        extension = '.png'
        
        try:
            if PILLOW_AVAILABLE:
                code128 = Code128(barcode_number, writer=ImageWriter())
                options = {
                    'module_width': 0.4,
                    'module_height': 20.0,
                    'quiet_zone': 6.5,
                    'font_size': 10,
                    'text_distance': 5.0,
                    'write_text': True,
                }
                local_filepath = code128.save(f"temp_barcode_{product_id}", options=options)
                extension = '.png'
            elif SVGWRITER_AVAILABLE:
                code128 = Code128(barcode_number, writer=SVGWriter())
                local_filepath = code128.save(f"temp_barcode_{product_id}")
                extension = '.svg'

            if not local_filepath:
                return None, None

            # Upload to Cloudinary
            public_id = f"quicktrolly/products/barcode_{product_id}_{barcode_number}"
            upload_result = cloudinary.uploader.upload(
                local_filepath,
                public_id=public_id,
                overwrite=True,
                resource_type="image"
            )
            secure_url = upload_result.get('secure_url')
            return secure_url, public_id

        except Exception as e:
            print(f"❌ Cloudinary barcode upload error: {e}")
            traceback.print_exc()
            return None, None
        finally:
            # Clean up local file
            if local_filepath and os.path.exists(local_filepath):
                try:
                    os.remove(local_filepath)
                except Exception as e:
                    print(f"Error deleting local temp file: {e}")

    def _init_admin(self):
        self.cursor.execute('SELECT id FROM qt_users WHERE email = %s', ('admin',))
        if not self.cursor.fetchone():
            hashed_pw = generate_password_hash("admin123")
            self.cursor.execute('''
                INSERT INTO qt_users (name, email, password, role, cart)
                VALUES (%s, %s, %s, %s, %s)
            ''', ("Admin User", "admin", hashed_pw, "admin", "[]"))
            print("✅ Default Admin Created: admin / admin123")

    def create_user(self, name, email, password):
        self.cursor.execute('SELECT id FROM qt_users WHERE email = %s', (email,))
        if self.cursor.fetchone():
            return False

        hashed_pw = generate_password_hash(password)
        try:
            self.cursor.execute('''
                INSERT INTO qt_users (name, email, password, role, cart)
                VALUES (%s, %s, %s, %s, %s)
            ''', (name, email, hashed_pw, "user", "[]"))
            return True
        except psycopg2.IntegrityError:
            return False

    def verify_user(self, email, password):
        self.cursor.execute('SELECT * FROM qt_users WHERE email = %s', (email,))
        user = self.cursor.fetchone()
        if user and check_password_hash(user['password'], password):
            return dict(user)
        return None

    def get_user_cart(self, user_id):
        self.cursor.execute('SELECT cart FROM qt_users WHERE id = %s', (user_id,))
        row = self.cursor.fetchone()
        if row:
            try:
                return json.loads(row['cart'])
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def update_user_cart(self, user_id, cart_data):
        cart_json = json.dumps(cart_data)
        self.cursor.execute('UPDATE qt_users SET cart = %s WHERE id = %s', (cart_json, user_id))

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
        self.cursor.execute('UPDATE qt_users SET cart = %s WHERE id = %s', ("[]", user_id))

    def get_all_products(self):
        self.cursor.execute('SELECT * FROM qt_products ORDER BY created_at DESC')
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products

    def get_product_by_qr(self, qr_code):
        self.cursor.execute('SELECT * FROM qt_products WHERE qr_code = %s', (qr_code,))
        row = self.cursor.fetchone()
        if row:
            product = dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def get_product_by_barcode(self, barcode_number):
        self.cursor.execute('SELECT * FROM qt_products WHERE barcode_number = %s', (barcode_number,))
        row = self.cursor.fetchone()
        if row:
            product = dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def get_product_by_id(self, product_id):
        self.cursor.execute('SELECT * FROM qt_products WHERE id = %s', (product_id,))
        row = self.cursor.fetchone()
        if row:
            product = dict(row)
            product['_id'] = str(product['id'])
            return product
        return None

    def add_product(self, name, original_price, price, qr_code, image_url):
        barcode_number = self._generate_unique_barcode()
        self.cursor.execute('''
            INSERT INTO qt_products (name, original_price, price, qr_code, image, barcode_number, barcode_image, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (name, float(original_price), float(price), qr_code, image_url, barcode_number, None, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        product_id = self.cursor.fetchone()['id']
        
        # Generate and upload barcode
        barcode_image, barcode_public_id = self._upload_barcode_to_cloudinary(barcode_number, product_id)

        self.cursor.execute('UPDATE qt_products SET barcode_image = %s, barcode_public_id = %s WHERE id = %s', 
                            (barcode_image, barcode_public_id, product_id))
        return str(product_id)

    def update_product(self, product_id, name, original_price, price, qr_code, image_url):
        existing = self.get_product_by_id(product_id)
        if not existing:
            return

        barcode_number = existing.get('barcode_number')
        barcode_image = existing.get('barcode_image')

        if not barcode_number:
            barcode_number = self._generate_unique_barcode()
            barcode_image, barcode_public_id = self._upload_barcode_to_cloudinary(barcode_number, product_id)
            self.cursor.execute('UPDATE qt_products SET barcode_public_id = %s WHERE id = %s', (barcode_public_id, product_id))

        self.cursor.execute('''
            UPDATE qt_products
            SET name = %s, original_price = %s, price = %s, qr_code = %s, image = %s, barcode_number = %s,
                barcode_image = %s, updated_at = %s
            WHERE id = %s
        ''', (name, float(original_price), float(price), qr_code, image_url, barcode_number, barcode_image,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), product_id))

    def delete_product(self, product_id):
        product = self.get_product_by_id(product_id)
        if product:
            # Delete barcode from Cloudinary
            if product.get('barcode_public_id'):
                try:
                    cloudinary.uploader.destroy(product['barcode_public_id'])
                except Exception as e:
                    print(f"Error deleting Cloudinary barcode: {e}")

        self.cursor.execute('DELETE FROM qt_products WHERE id = %s', (product_id,))
        return self.cursor.rowcount > 0

    def regenerate_barcode(self, product_id):
        product = self.get_product_by_id(product_id)
        if not product:
            return None

        # Delete old barcode from Cloudinary
        if product.get('barcode_public_id'):
            try:
                cloudinary.uploader.destroy(product['barcode_public_id'])
            except Exception as e:
                print(f"Error deleting old Cloudinary barcode: {e}")

        barcode_number = self._generate_unique_barcode()
        barcode_image, barcode_public_id = self._upload_barcode_to_cloudinary(barcode_number, product_id)

        self.cursor.execute('''
            UPDATE qt_products
            SET barcode_number = %s, barcode_image = %s, barcode_public_id = %s
            WHERE id = %s
        ''', (barcode_number, barcode_image, barcode_public_id, product_id))
        return {"barcode_number": barcode_number, "barcode_image": barcode_image}

    def create_order(self, customer_name, phone, address, products, total, email=None, payment_id=None):
        products_json = json.dumps(products)
        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.cursor.execute('''
            INSERT INTO qt_orders (customer_name, phone, address, email, payment_id, products, total, date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (customer_name, phone, address, email, payment_id, products_json, total, order_date, "Pending"))
        
        order_id = self.cursor.fetchone()['id']
        return str(order_id)

    def get_order_by_id(self, order_id):
        self.cursor.execute('SELECT * FROM qt_orders WHERE id = %s', (order_id,))
        row = self.cursor.fetchone()
        if row:
            order = dict(row)
            order['_id'] = str(order['id'])
            try:
                order['products'] = json.loads(order['products'])
            except (json.JSONDecodeError, TypeError):
                order['products'] = []
            return order
        return None

    def get_all_orders(self):
        self.cursor.execute('SELECT * FROM qt_orders ORDER BY date DESC')
        rows = self.cursor.fetchall()
        orders = []
        for row in rows:
            order = dict(row)
            order['_id'] = str(order['id'])
            try:
                order['products'] = json.loads(order['products'])
            except (json.JSONDecodeError, TypeError):
                order['products'] = []
            orders.append(order)
        return orders

    def update_order_status(self, order_id, status):
        self.cursor.execute('UPDATE qt_orders SET status = %s WHERE id = %s', (status, order_id))

    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM qt_products')
        total_products = self.cursor.fetchone()['count']
        self.cursor.execute('SELECT COUNT(*) FROM qt_orders')
        total_orders = self.cursor.fetchone()['count']
        return total_products, total_orders

    def get_user_count(self):
        self.cursor.execute('SELECT COUNT(*) FROM qt_users')
        return self.cursor.fetchone()['count']

    def get_recent_products(self, limit=5):
        self.cursor.execute('SELECT * FROM qt_products ORDER BY created_at DESC LIMIT %s', (limit,))
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products

    def search_products(self, search_term):
        search_pattern = f'%{search_term}%'
        self.cursor.execute('''
            SELECT * FROM qt_products
            WHERE name LIKE %s OR qr_code LIKE %s OR barcode_number LIKE %s
            ORDER BY created_at DESC
        ''', (search_pattern, search_pattern, search_pattern))
        rows = self.cursor.fetchall()
        products = []
        for row in rows:
            product = dict(row)
            product['_id'] = str(product['id'])
            products.append(product)
        return products

    def _generate_unique_barcode(self):
        while True:
            barcode_num = ''.join([str(random.randint(0, 9)) for _ in range(12)])
            self.cursor.execute('SELECT id FROM qt_products WHERE barcode_number = %s', (barcode_num,))
            if not self.cursor.fetchone():
                return barcode_num

db = Database()
