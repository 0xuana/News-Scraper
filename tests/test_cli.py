from collector.__main__ import _parser


def test_parser_accepts_scheduled_command() -> None:
    assert _parser().parse_args(["scheduled"]).command == "scheduled"


def test_backfill_before_is_a_unix_timestamp() -> None:
    args = _parser().parse_args(["backfill", "--before", "1789617870"])

    assert args.before == 1789617870
