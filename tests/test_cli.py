from inreach.cli import main


def test_hello_command_prints_hello(capsys):
    main(["hello"])
    assert capsys.readouterr().out.strip() == "hello"


def test_no_command_prints_help(capsys):
    main([])
    assert "usage" in capsys.readouterr().out.lower()
