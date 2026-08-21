from inreach.app.setup import vdf

SAMPLE = r"""
"UserLocalConfigStore"
{
	"streaming_v2"
	{
		"EnableStreaming"		"1"
	}
	"friends"
	{
		"75830121"
		{
			"NameHistory"
			{
				"0"		"PaPa Smurf"
			}
			"name"		"PaPa Smurf"
		}
		"PersonaName"		"PaPa Smurf"
		"communitypreferences"		"18002000280130013800"
	}
}
"""


def test_loads_nested_structure():
    data = vdf.loads(SAMPLE)

    assert data["UserLocalConfigStore"]["streaming_v2"]["EnableStreaming"] == "1"
    assert data["UserLocalConfigStore"]["friends"]["PersonaName"] == "PaPa Smurf"
    assert data["UserLocalConfigStore"]["friends"]["75830121"]["name"] == "PaPa Smurf"


def test_loads_handles_escaped_quotes():
    text = '"root" { "key" "a \\"quoted\\" value" }'

    data = vdf.loads(text)

    assert data["root"]["key"] == 'a "quoted" value'


def test_loads_empty_text_returns_empty_dict():
    assert vdf.loads("") == {}
