from network_inventory.cli import main


def test_main_without_command_succeeds(capsys):
    assert main([]) == 0
    assert "network-inventory" in capsys.readouterr().out
