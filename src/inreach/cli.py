import argparse

from inreach.core import hello


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="inreach")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("hello", help="Print a hello message")

    args = parser.parse_args(argv)

    if args.command == "hello":
        print(hello())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
