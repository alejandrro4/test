from poker_bot.cli import main


def test_cli_preflop(capsys):
    assert main(["pre", "AsKd", "--pos", "CO"]) == 0
    assert "SUBIR" in capsys.readouterr().out


def test_cli_postflop(capsys):
    assert main(["post", "4c3c", "--board", "KdQhJs", "--pot", "9.5", "--call", "4", "--ms", "300"]) == 0
    assert "TIRAR" in capsys.readouterr().out


def test_cli_error(capsys):
    assert main(["pre", "AsKd", "--pos", "UTG", "--opener", "CO"]) == 2
