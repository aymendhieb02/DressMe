from sqlalchemy import inspect, text
from app.database import engine

cols = [c["name"] for c in inspect(engine).get_columns("users")]
print("Base :", engine.url)
print("Colonnes actuelles :", cols)

if "gender" in cols:
    print("La colonne gender existe déjà, rien à faire.")
else:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN gender VARCHAR(20)"))
    print("Colonne gender ajoutée.")