from in_reach.app import vdf


def test_loads_nested_blocks_and_pairs() -> None:
    text = """
    "UserLocalConfigStore"
    {
        "friends"
        {
            "PersonaName"   "Whiley"
        }
        "Software"
        {
            "Valve"  { "Steam" { "language" "english" } }
        }
    }
    """

    data = vdf.loads(text)

    assert data["UserLocalConfigStore"]["friends"]["PersonaName"] == "Whiley"
    assert data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["language"] == "english"


def test_loads_unescapes_quotes_and_backslashes() -> None:
    data = vdf.loads(r'"root" { "path" "C:\\Users\\me" "quoted" "say \"hi\"" }')

    assert data["root"]["path"] == r"C:\Users\me"
    assert data["root"]["quoted"] == 'say "hi"'


def test_loads_returns_an_empty_dict_for_junk() -> None:
    assert vdf.loads("not vdf at all") == {}
