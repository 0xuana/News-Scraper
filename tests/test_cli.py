from collector.__main__ import _parser


def test_parser_accepts_scheduled_command() -> None:
    assert _parser().parse_args(["scheduled"]).command == "scheduled"
