import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'quicktrolly-secret-key-2026'
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'postgresql://user:password@localhost:5432/quicktrolly_db'
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID') or 'rzp_test_dhYJFlohg88eyl'
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET') or 'YOUR_SECRET_KEY_HERE'

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

    # Automatically parse CLOUDINARY_URL if individual variables are missing
    CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
    if CLOUDINARY_URL and not CLOUDINARY_CLOUD_NAME:
        try:
            # Format: cloudinary://<api_key>:<api_secret>@<cloud_name>
            parts = CLOUDINARY_URL.replace('cloudinary://', '').split('@')
            if len(parts) == 2:
                auth_part = parts[0]
                cloud_name = parts[1]
                key_parts = auth_part.split(':')
                if len(key_parts) == 2:
                    CLOUDINARY_API_KEY = key_parts[0]
                    CLOUDINARY_API_SECRET = key_parts[1]
                    CLOUDINARY_CLOUD_NAME = cloud_name
        except Exception as e:
            print(f"⚠️ Error parsing CLOUDINARY_URL: {e}")
