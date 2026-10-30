from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_initial_migration_upgrades_an_empty_sqlite_database(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "users", "auth_sessions", "garments", "storage_deletions", "avatar_consents", "avatars", "avatar_renders", "alembic_version",
        } <= tables
    finally:
        engine.dispose()


def test_garment_data_survives_contract_migration(tmp_path, monkeypatch):
    database_path = tmp_path / "populated.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0003_refresh_families")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO users (id, email, password_hash, role, created_at, updated_at)
                VALUES ('u1', 'alice@example.com', 'hash', 'USER', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
            connection.execute(text("""
                INSERT INTO pending_uploads (
                    id, user_id, image_key, content_type, image_sha256, width, height,
                    quality_snapshot, prediction_snapshot, model_version, taxonomy_version,
                    description_version, quality_version, expires_at
                ) VALUES (
                    'p1', 'u1', '00000000000000000000000000000001.png', 'image/png', 'hash', 20, 30,
                    '{}', '{}', 'model', 'dressme-v0.2', 'description', 'quality', CURRENT_TIMESTAMP
                )
            """))
            connection.execute(text("""
                INSERT INTO garments (
                    id, user_id, pending_upload_id, image_key, category, description,
                    description_is_manual, prediction_snapshot, quality_snapshot, field_sources,
                    was_corrected, model_version, taxonomy_version, description_version
                ) VALUES (
                    'g1', 'u1', 'p1', '00000000000000000000000000000001.png', 'shirt', 'blue shirt',
                    0, '{}', '{}', '{}', '{}', 'model', 'dressme-v0.2', 'description'
                )
            """))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT category, garment_photo_type, vton_eligibility FROM garments WHERE id = 'g1'")).one()
            assert row.category == "shirt"
            assert row.garment_photo_type == "flat-lay"
            assert row.vton_eligibility == "{}"
    finally:
        engine.dispose()
