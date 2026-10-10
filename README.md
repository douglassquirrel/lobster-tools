# lobster-tools

Tools for "lobster coding": having an LLM do a kind of task and, as it goes, build up an
exoskeleton of small, well-tested tools that a person or the bot can use the next time that kind
of task comes round. Each tool is a command-line program for a stock Mac (Python 3.9 standard
library, no daemon, no network), built test-first from a need met in real work.

**Nothing is built yet.** The first tool will be `lobster-mail`, a file-based mail system that
lets the LLM working in one project send a request to the LLM working in another and get a reply:
one folder per mailbox, one Markdown file per message, state kept as the folder a message is in,
and nothing ever edited, deleted or executed.

This README will grow into the full guide (requirements, installation, usage, exit codes, testing)
as the tools are built.
