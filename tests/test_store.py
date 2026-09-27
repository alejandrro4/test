import pytest

from poker_bot.stats.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_amigos_crud(store):
    store.save_friend("Pepe", "calling station")
    store.save_friend("Ana", "se tira mucho")
    assert [f["name"] for f in store.list_friends()] == ["Ana", "Pepe"]
    store.save_friend("Pepe", "maníaco")   # actualizar
    assert store.profile("Pepe").style == "maníaco"
    store.delete_friend("Ana")
    assert store.profile("Ana") is None


def test_amigo_invalido(store):
    with pytest.raises(ValueError):
        store.save_friend("  ", "normal")
    with pytest.raises(ValueError):
        store.save_friend("Luis", "inventado")


def test_perfiles_por_estilo(store):
    store.save_friend("Pepe", "calling station")
    p = store.profiles(["Pepe", "Nadie"])
    assert list(p) == ["Pepe"] and p["Pepe"].fold_factor < 0.7


def test_registro(store):
    store.log_decision(street="flop", hero=["As", "Kd"], board=["Qh", "7c", "2d"], rivals=["Pepe"],
                       action="bet", amount_bb=3.0, equity=0.6, ev_bb=1.2, reason="x", request={})
    (row,) = store.recent_decisions()
    assert row["hero"] == "AsKd" and row["board"] == "Qh7c2d" and row["action"] == "bet"
