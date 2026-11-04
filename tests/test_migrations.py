from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import pytest
from sqlalchemy.exc import IntegrityError


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
            "users", "auth_sessions", "password_recovery_challenges", "garments", "storage_deletions", "avatar_consents", "avatars", "avatar_renders", "alembic_version",
        } <= tables
    finally:
        engine.dispose()


def test_gender_migration_preserves_existing_account_and_session(tmp_path, monkeypatch):
    database_url=f"sqlite:///{(tmp_path/'gender.db').as_posix()}"
    monkeypatch.setenv('DATABASE_URL',database_url)
    config=Config('alembic.ini')
    command.upgrade(config,'0009_password_recovery')
    engine=create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id,email,password_hash,role,created_at,updated_at) VALUES ('u1','existing@example.com','hash','USER',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO auth_sessions (id,user_id,token_hash,csrf_hash,expires_at) VALUES ('s1','u1','token','csrf','2099-01-01')"))
    command.upgrade(config,'head')
    with engine.begin() as connection:
        assert connection.execute(text('SELECT gender FROM users WHERE id=\'u1\'')).scalar() is None
        assert connection.execute(text('SELECT user_id FROM auth_sessions WHERE id=\'s1\'')).scalar()=='u1'
        connection.execute(text("UPDATE users SET gender='women' WHERE id='u1'"))
    command.downgrade(config,'0009_password_recovery')
    with engine.connect() as connection:
        assert connection.execute(text("SELECT email FROM users WHERE id='u1'")).scalar()=='existing@example.com'
        assert connection.execute(text("SELECT user_id FROM auth_sessions WHERE id='s1'")).scalar()=='u1'
    engine.dispose()


def test_binary_gender_migration_preserves_choices_and_clears_old_third_choice(tmp_path, monkeypatch):
    database_url=f"sqlite:///{(tmp_path/'binary-gender.db').as_posix()}"
    monkeypatch.setenv('DATABASE_URL',database_url)
    config=Config('alembic.ini')
    command.upgrade(config,'0010_user_gender')
    engine=create_engine(database_url)
    with engine.begin() as connection:
        for index,gender in enumerate(('men','women','unisex')):
            connection.execute(text("INSERT INTO users (id,email,password_hash,role,gender,created_at,updated_at) VALUES (:id,:email,'hash','USER',:gender,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),
                               dict(id=f'u{index}',email=f'user{index}@example.com',gender=gender))
    command.upgrade(config,'head')
    with engine.connect() as connection:
        assert dict(connection.execute(text('SELECT id,gender FROM users')).all())=={'u0':'men','u1':'women','u2':None}
    with pytest.raises(IntegrityError),engine.begin() as connection:
        connection.execute(text("UPDATE users SET gender='unisex' WHERE id='u0'"))
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
