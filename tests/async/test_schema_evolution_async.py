import pytest
from pydantic import BaseModel, Field

from memstate import AsyncInMemoryStorage, AsyncMemoryStore


class UserProfileV1(BaseModel):
    username: str
    # the `role` field is missing yet


class UserProfileV2(BaseModel):
    username: str
    role: str = Field(default="user")


class UserProfileV3_Strict(BaseModel):
    username: str
    age: int  # a new field without a default value


class UserProfileV4(BaseModel):
    username: str


@pytest.fixture
def memory():
    return AsyncMemoryStore(AsyncInMemoryStorage())


async def test_schema_evolution_adding_field_with_default(memory):
    memory.register_schema("user", UserProfileV1)

    id_v1 = await memory.commit_model(UserProfileV1(username="legacy_user"))

    memory.register_schema("user", UserProfileV2)

    fact_data = await memory.storage.load(id_v1)
    raw_payload = fact_data["payload"]

    user_obj = UserProfileV2(**raw_payload)

    assert user_obj.username == "legacy_user"
    assert user_obj.role == "user"

    id_v2 = await memory.commit_model(UserProfileV2(username="new_user", role="admin"))

    raw_payload_v2 = await memory.storage.load(id_v2)
    assert raw_payload_v2["payload"]["role"] == "admin"


async def test_schema_breaking_change(memory):
    memory.register_schema("user", UserProfileV1)
    id_v1 = await memory.commit_model(UserProfileV1(username="young_user"))

    memory.register_schema("user", UserProfileV3_Strict)

    fact_data = await memory.storage.load(id_v1)

    with pytest.raises(ValueError) as excinfo:
        UserProfileV3_Strict(**fact_data["payload"])

    assert "age" in str(excinfo.value)
    assert "Field required" in str(excinfo.value)


async def test_loading_rich_data_into_slim_model(memory):
    memory.register_schema("user", UserProfileV2)
    rich_id = await memory.commit_model(UserProfileV2(username="rich_user", role="admin"))

    memory.register_schema("user", UserProfileV4)

    fact_data = await memory.storage.load(rich_id)

    user_obj = UserProfileV4(**fact_data["payload"])

    assert user_obj.username == "rich_user"
    assert not hasattr(user_obj, "role")
