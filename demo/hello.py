import django
import os
import dotenv

dotenv.load_dotenv(override=True)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo.settings')

django.setup()