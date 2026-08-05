from utils import todo_data


def test_process_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(todo_data, "CACHE_MAX_ENTRIES", 2)
    todo_data._cache.clear()

    todo_data.cache_put("player:#ONE", object(), 600)
    todo_data.cache_put("player:#TWO", object(), 600)
    todo_data.cache_put("player:#THREE", object(), 600)

    assert len(todo_data._cache) == 2
    assert "player:#THREE" in todo_data._cache
    todo_data._cache.clear()
