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
