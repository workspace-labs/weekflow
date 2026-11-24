# Working on weekflow

Read [Scope](docs/scope.md) and [Security](docs/security.md) before changing the tool. The [engineering decisions](docs/adr/) explain the weekly record, meeting pages, PDFs and recovery behavior.

Keep the skill self-contained in `skills/weekflow/`. Start with the [skill instructions](skills/weekflow/SKILL.md) and its [command-line entry point](skills/weekflow/scripts/weekflow.py). Keep the runtime offline and write project records under `docs/weekly/`. Run one command at a time against a project.

From the repository root, run `python3 -m unittest discover -s tests` with Python 3.9 and the current Python. Use disposable copies of the sample project. The [README](README.md#how-it-was-tested) lists the tools used by the PDF tests and shows how to try a meeting.
