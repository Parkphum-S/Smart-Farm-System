import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv(".env")
url = make_url(os.environ["SMARTFARM_MIGRATION_DATABASE_URL"])
print(url.set(database="smartfarm_test").render_as_string(hide_password=False))
