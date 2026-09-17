import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'quicktrolly-secret-key-2026'
    DATABASE = os.environ.get('DATABASE') or 'quicktrolly_db.sqlite'
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID') or 'rzp_test_dhYJFlohg88eyl'
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET') or 'YOUR_SECRET_KEY_HERE'