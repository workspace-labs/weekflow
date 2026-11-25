#!/usr/bin/env python3
"""Run the local weekly meeting commands."""

import argparse
from itertools import islice
import re
import sys

sys.dont_write_bytecode = True

from weekflow_tool.changes import change
from weekflow_tool.corrections import correct
from weekflow_tool.handoff import handoff
from weekflow_tool.lock_transaction import recover_transactions
from weekflow_tool.meeting_design import PDF_PAPERS
from weekflow_tool.meetings import (
    check_prepare_content, confirm, correct_date, enter_build, no_meeting, prepare, screen_picture,
)
from weekflow_tool.picture_removal import remove_picture
from weekflow_tool.promises import check_promise
from weekflow_tool.records import client_copy, lock, record, sign
from weekflow_tool.removal import removal_receipt, remove_name
from weekflow_tool.screens import check_picture, import_flow, upsert_screen
from weekflow_tool.setup import start
from weekflow_tool.storage import ProjectFiles, Refusal


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refusal(message)


def whole_days(value):
    if re.fullmatch(r"[0-9]+", value):
        try:
            return int(value)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("Give --days as a whole number of 0 or more.")


def week_number(value):
    if re.fullmatch(r"[1-9][0-9]*", value):
        try:
            return int(value)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("Give --week as a whole number starting at 1.")


def screen_order(value):
    try:
        return week_number(value)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError("Give --order as a whole number starting at 1.") from None


def literal_delay_values(argv):
    """Keep the four delay values from being parsed as flags by Python 3.9."""
    remaining = iter(argv)
    for argument in remaining:
        yield argument
        if argument == "--":
            yield from remaining
            return
        if argument == "--delay":
            yield from (" " + value for value in islice(remaining, 4))


def arguments(argv):
    parser = Parser(description="Prepare a weekly client meeting from local project files.")
    commands = parser.add_subparsers(required=True, dest="command")
    for action, name in ((start, "start"), (enter_build, "enter-build"), (correct_date, "correct-date"),
                         (change, "change"), (prepare, "prepare"),
                         (confirm, "confirm"), (record, "record"), (client_copy, "client-copy"),
                         (sign, "sign"), (lock, "lock"), (check_promise, "check-promise"),
                         (no_meeting, "no-meeting"), (correct, "correct"), (remove_name, "remove-name"),
                         (import_flow, "screens-from-flow"), (upsert_screen, "screen"),
                         (screen_picture, "screen-picture"), (check_picture, "screen-check"),
                         (remove_picture, "remove-picture"), (handoff, "handoff")):
        command = commands.add_parser(name, allow_abbrev=name != "handoff")
        command.add_argument("project", help="the project folder")
        command.set_defaults(action=action)

    start_args, change_args, prepare_args = (commands.choices[name] for name in ("start", "change", "prepare"))
    start_args.add_argument("--client")
    start_args.add_argument("--meeting-day")
    start_args.add_argument("--language", choices=("en", "ar"))
    start_args.add_argument("--attendee", nargs="+", action="extend")
    start_args.add_argument("--planned-end")
    start_args.add_argument("--project", dest="project_name", help="the project name if it is missing from the documents")
    commands.choices["enter-build"].add_argument("--planned-end")
    commands.choices["correct-date"].add_argument("--planned-end", required=True)
    change_args.add_argument("--what")
    change_args.add_argument("--reason")
    change_args.add_argument("--asked-by")
    change_args.add_argument("--days", type=whole_days)
    change_args.add_argument("--id")
    prepare_args.add_argument("--content", required=True)
    prepare_args.add_argument("--date", required=True)
    prepare_args.add_argument("--pdf-paper", choices=PDF_PAPERS, help="the owner's choice of PDF paper")
    colour_choice = prepare_args.add_mutually_exclusive_group()
    colour_choice.add_argument("--colors", choices=("standard",), help="use the standard colours")
    colour_choice.add_argument("--main-color", help="the owner's main colour as #RRGGBB")
    prepare_args.add_argument("--background-color", help="optional background with --main-color")
    prepare_args.add_argument("--text-color", help="optional text colour with --main-color")
    record_args = commands.choices["record"]
    answer_route = record_args.add_mutually_exclusive_group(required=True)
    answer_route.add_argument("--answers")
    answer_route.add_argument("--answer", action="append", nargs="?", const="")
    record_args.add_argument("--attendee", action="append", required=True)
    record_args.add_argument("--decided-by")
    sign_args = commands.choices["sign"]
    sign_args.add_argument("--by", required=True)
    sign_args.add_argument("--on", required=True)
    promise_args = commands.choices["check-promise"]
    promise_args.add_argument("--id", required=True)
    promise_args.add_argument("--status", choices=("done", "not-finished"), required=True)
    promise_args.add_argument("--note")
    commands.choices["no-meeting"].add_argument("--date", required=True)
    commands.choices["correct"].add_argument("--week", type=week_number, required=True)
    name_removal = commands.choices["remove-name"]
    name_removal.add_argument("--name", required=True)
    name_removal.add_argument("--also", action="append", default=[], help="remove an owner-approved listed word")
    name_removal.add_argument("--keep", action="append", default=[], help="keep an owner-approved listed word")
    for name in ("correct", "remove-name", "remove-picture"):
        for flag in ("--what", "--reason", "--by"):
            commands.choices[name].add_argument(flag, required=True)
    for name in ("screen", "screen-picture", "screen-check", "remove-picture"):
        commands.choices[name].add_argument("--id", required=True)
    screen_args = commands.choices["screen"]
    screen_args.add_argument("--name")
    screen_args.add_argument("--order", type=screen_order)
    screen_args.add_argument("--state", choices=("finished", "being-built", "not-built"))
    picture_args = commands.choices["screen-picture"]
    picture_args.add_argument("--file", required=True)
    picture_args.add_argument("--kind", choices=("screenshot", "design"), required=True)
    picture_args.add_argument("--taken-on")
    commands.choices["screen-check"].add_argument("--file", help="an exact saved picture path under screens/")
    commands.choices["remove-picture"].add_argument("--file", required=True)
    handoff_args = commands.choices["handoff"]
    handoff_args.add_argument("--start", required=True, help="the project start date given by the owner")
    handoff_args.add_argument("--real-end", required=True, help="the actual end date given by the owner")
    handoff_args.add_argument("--delay", action="append", nargs=4, default=[], type=lambda value: value[1:],
                              metavar=("DATE", "WHAT", "DAYS", "REASON"),
                              help="an owner-given event with signed calendar days. Repeat for more events")
    handoff_args.add_argument("--confirmed", action="store_true", help="the owner confirmed the entire list")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "handoff":
        argv = list(literal_delay_values(argv))
    return parser.parse_args(argv)


def refuse(messages):
    for number, message in enumerate(messages, start=1):
        line = " ".join(message.split())
        if line[-1] not in ".!?":
            line += "."
        print(f"{number}. {line[0].upper() + line[1:]}", file=sys.stderr)
    return 2


def use_utf8_output():
    # Windows pipes default to the ANSI code page, which cannot print arrows or Arabic.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv=None):
    use_utf8_output()
    try:
        args = arguments(argv)
        files = ProjectFiles(args.project)
        with files.command():
            options = {}
            if args.command == "prepare":
                options["secret_check"] = check_prepare_content(files, args.content)
            if args.command != "handoff":
                recovery = recover_transactions(files)
                if recovery is not None:
                    messages = removal_receipt(recovery.weeks, recovered=True, picture=recovery.picture)
                    for message in messages + recovery.warnings:
                        print(message)
            messages = args.action(files, args, **options)
    except Refusal as error:
        return refuse(error.messages)
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return refuse(["Check that the project files and paths can be read or written as needed."])
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
