from alembic.config import Config
from alembic.script import ScriptDirectory


def test_document_migration_follows_initial_migration():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260928_0012"]
    assert script.get_base() == "20260915_0001"
    assert script.get_revision("20260915_0001").down_revision is None
    assert script.get_revision("20260921_0002").down_revision == "20260915_0001"
    assert script.get_revision("20260921_0003").down_revision == "20260921_0002"
    assert script.get_revision("20260922_0004").down_revision == "20260921_0003"
    assert script.get_revision("20260922_0005").down_revision == "20260922_0004"
    assert script.get_revision("20260924_0006").down_revision == "20260922_0005"
    assert script.get_revision("20260925_0007").down_revision == "20260924_0006"
    assert script.get_revision("20260925_0008").down_revision == "20260925_0007"
    assert script.get_revision("20260925_0009").down_revision == "20260925_0008"
    assert script.get_revision("20260925_0010").down_revision == "20260925_0009"
    assert script.get_revision("20260925_0011").down_revision == "20260925_0010"
    assert script.get_revision("20260928_0012").down_revision == "20260925_0011"
