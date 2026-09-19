"""تست‌های ذخیره‌سازی گفتگوها در SQLite."""

from app.services.storage import ConversationStore, normalise_title


def make_store(tmp_path):
    return ConversationStore(tmp_path / "nested" / "assistant.db")


def test_store_creates_database_file_and_schema(tmp_path):
    store = make_store(tmp_path)

    assert store.database_path.is_file()
    assert store.latest_conversation() is None
    assert store.load_messages(1) == []


def test_exchange_round_trip(tmp_path):
    store = make_store(tmp_path)
    conversation_id = store.create_conversation("اولین گفتگو")

    store.add_exchange(conversation_id, "سلام", "درود")

    assert store.load_messages(conversation_id) == [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "درود"},
    ]


def test_latest_conversation_is_the_recently_updated_one(tmp_path):
    store = make_store(tmp_path)
    first = store.create_conversation("اول")
    second = store.create_conversation("دوم")

    store.add_exchange(first, "الف", "ب")
    store.add_exchange(second, "پ", "ت")

    assert store.latest_conversation().id == second

    store.add_exchange(first, "ادامه", "پاسخ")

    latest = store.latest_conversation()
    assert latest.id == first
    assert latest.title == "اول"


def test_list_conversations_orders_by_newest_message(tmp_path):
    store = make_store(tmp_path)
    first = store.create_conversation("اول")
    second = store.create_conversation("دوم")
    third = store.create_conversation("سوم")

    store.add_exchange(first, "الف", "ب")
    store.add_exchange(second, "پ", "ت")
    store.add_exchange(third, "ج", "چ")
    assert [item.id for item in store.list_conversations()] == [third, second, first]

    store.add_exchange(first, "ادامه", "پاسخ")

    assert [item.id for item in store.list_conversations()] == [first, third, second]
    assert [item.title for item in store.list_conversations(limit=2)] == ["اول", "سوم"]


def test_delete_conversation_removes_its_messages(tmp_path):
    store = make_store(tmp_path)
    first = store.create_conversation("اول")
    second = store.create_conversation("دوم")
    store.add_exchange(first, "الف", "ب")
    store.add_exchange(second, "پ", "ت")

    store.delete_conversation(first)

    assert store.load_messages(first) == []
    assert [item.id for item in store.list_conversations()] == [second]
    assert store.latest_conversation().id == second


def test_data_survives_reopening_the_database(tmp_path):
    path = tmp_path / "assistant.db"
    store = ConversationStore(path)
    conversation_id = store.create_conversation("گفتگوی ماندگار")
    store.add_exchange(conversation_id, "سلام", "درود")
    store.close()

    reopened = ConversationStore(path)

    assert reopened.latest_conversation().title == "گفتگوی ماندگار"
    assert reopened.load_messages(conversation_id) == [
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "درود"},
    ]


def test_normalise_title_collapses_whitespace_and_truncates():
    assert normalise_title("  سلام   دنیا  ") == "سلام دنیا"
    assert normalise_title("") == "گفتگوی بدون عنوان"
    assert normalise_title("   ") == "گفتگوی بدون عنوان"

    long_title = normalise_title("س" * 200, max_length=20)
    assert len(long_title) == 20
    assert long_title.endswith("…")
