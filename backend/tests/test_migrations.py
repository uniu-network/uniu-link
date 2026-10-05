import asyncio
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import database


BACKEND_DIR = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
BASELINE = "20260530_0001"
OLD_REVISIONS = ("20260616_0001", "20260616_0002", "20260621_0001")


def migration_config(connection=None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite://")
        self.connection = self.engine.connect()
        self.config = migration_config(self.connection)

    def tearDown(self):
        self.connection.close()
        self.engine.dispose()

    def assert_schema_matches_models(self):
        context = MigrationContext.configure(self.connection)
        self.assertEqual(
            context.get_current_heads(),
            tuple(ScriptDirectory.from_config(self.config).get_heads()),
        )
        # env.py imports all model classes. Compare columns, types, nullability,
        # indexes and foreign keys, not just whether the tables were created.
        self.assertEqual(compare_metadata(context, database.Base.metadata), [])
        self.assertEqual(len(database.Base.metadata.tables), 6)

    def insert_fixture(self, table_name, **overrides):
        table = sa.Table(table_name, sa.MetaData(), autoload_with=self.connection)
        values = {}
        for column in table.columns:
            if column.nullable or column.server_default is not None:
                continue
            if isinstance(column.type, sa.Boolean):
                values[column.name] = False
            elif isinstance(column.type, (sa.Integer, sa.Float)):
                values[column.name] = 0
            elif isinstance(column.type, sa.JSON):
                values[column.name] = []
            else:
                values[column.name] = ""
        values.update(overrides)
        self.connection.execute(table.insert().values(**values))

    def test_empty_database_upgrades_to_current_models(self):
        command.upgrade(self.config, "head")
        self.assert_schema_matches_models()

    def test_existing_revisions_preserve_data_and_upgrade_idempotently(self):
        for revision in (BASELINE, *OLD_REVISIONS):
            with self.subTest(revision=revision):
                command.upgrade(self.config, revision)
                self.insert_fixture("channels", id="channel-1", name="existing-channel",
                                    encrypted_api_key="existing-ciphertext")
                self.insert_fixture("model_configs", id="model-1", name="existing-model")
                self.insert_fixture("model_channel_refs", id="ref-1", model_id="model-1",
                                    channel_id="channel-1", upstream_model_id="upstream-model")
                self.insert_fixture("api_keys", id="key-1", key_hash="existing-hash", used_tokens=123)
                self.insert_fixture("plugins", id="plugin-1", module_path="existing.Plugin")
                self.insert_fixture("request_logs", id="log-1", trace_id="existing-trace", total_tokens=123)

                command.upgrade(self.config, "head")
                command.upgrade(self.config, "head")
                self.assert_schema_matches_models()
                self.assertEqual(self.connection.execute(sa.text(
                    "SELECT encrypted_api_key, health_check_mode FROM channels"
                )).one(), ("existing-ciphertext", "model_list"))
                self.assertEqual(self.connection.execute(sa.text(
                    "SELECT key_hash, used_tokens FROM api_keys"
                )).one(), ("existing-hash", 123))
                self.assertEqual(self.connection.execute(sa.text(
                    "SELECT trace_id, total_tokens, from_apikey FROM request_logs"
                )).one(), ("existing-trace", 123, ""))
                self.assertEqual(self.connection.execute(sa.text(
                    "SELECT model_id, channel_id, upstream_model_id FROM model_channel_refs"
                )).one(), ("model-1", "channel-1", "upstream-model"))
                self.assertEqual(self.connection.scalar(sa.text(
                    "SELECT icon FROM model_configs WHERE id = 'model-1'"
                )), "auto")
                self.assertEqual(self.connection.scalar(sa.text(
                    "SELECT module_path FROM plugins"
                )), "existing.Plugin")
                command.downgrade(self.config, "base")

    def test_downgrade_and_reupgrade(self):
        command.upgrade(self.config, "head")
        command.downgrade(self.config, BASELINE)
        inspector = sa.inspect(self.connection)
        self.assertIn("enable_cache", {c["name"] for c in inspector.get_columns("model_configs")})
        self.assertNotIn("health_check_mode", {c["name"] for c in inspector.get_columns("channels")})
        self.assertNotIn("from_apikey", {c["name"] for c in inspector.get_columns("request_logs")})
        self.assertNotIn("icon", {c["name"] for c in inspector.get_columns("model_configs")})
        command.downgrade(self.config, "base")
        self.assertEqual(sa.inspect(self.connection).get_table_names(), ["alembic_version"])
        command.upgrade(self.config, "head")
        self.assert_schema_matches_models()

    def test_manual_model_icon_survives_repeated_upgrade(self):
        command.upgrade(self.config, "head")
        self.insert_fixture("model_configs", id="custom-icon", name="alias", icon="qwen")
        self.connection.commit()
        command.upgrade(self.config, "head")
        self.assertEqual(self.connection.scalar(sa.text(
            "SELECT icon FROM model_configs WHERE id = 'custom-icon'"
        )), "qwen")

    def test_application_migration_entrypoint_is_independent_of_cwd(self):
        # The container and local checkout place alembic.ini in different roots.
        with patch("os.getcwd", return_value="/"):
            database._upgrade_schema(self.connection)
            database._upgrade_schema(self.connection)
        self.assert_schema_matches_models()

    def test_offline_upgrade_includes_baseline_before_alterations(self):
        config = migration_config(self.connection)
        output = io.StringIO()
        config.output_buffer = output
        command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        self.assertLess(sql.index("CREATE TABLE channels"), sql.index("ALTER TABLE channels"))
        self.assertIn("CREATE TABLE api_keys", sql)
        self.assertIn("20260621_0001", sql)


@unittest.skipUnless(POSTGRES_URL, "set TEST_POSTGRES_URL to run PostgreSQL migration tests")
class PostgresMigrationTests(MigrationTests):
    def setUp(self):
        self.schema = "migration_test_" + uuid.uuid4().hex
        self.engine = sa.create_engine(POSTGRES_URL)
        with self.engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(self.schema))
        self.connection = self.engine.connect()
        self.connection.execute(sa.text(f'SET search_path TO "{self.schema}"'))
        self.connection.commit()
        self.config = migration_config(self.connection)

    def tearDown(self):
        self.connection.close()
        with self.engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(self.schema, cascade=True))
        self.engine.dispose()

    def test_async_application_initialization_records_revision(self):
        async def initialize():
            url = sa.engine.make_url(POSTGRES_URL).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(url, connect_args={
                "server_settings": {"search_path": self.schema},
            })
            try:
                with patch.object(database, "engine", engine):
                    await database.init_db()
                    await database.init_db()
            finally:
                await engine.dispose()

        asyncio.run(initialize())
        self.assert_schema_matches_models()


if __name__ == "__main__":
    unittest.main()
