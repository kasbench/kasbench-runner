"""Manifest list (k8s.lst) parsing and serialization.

Parses k8s.lst files into typed operations and supports round-trip
serialization back to text format.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8, 19.9
"""

from dataclasses import dataclass
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ManifestOperation:
    """A single parsed operation from a k8s.lst file.

    Attributes:
        op_type: The classification of this line.
        raw_line: The original line text as read from the file.
        value: Typed payload depending on op_type:
            - manifest: the final filename (with .yaml appended if needed)
            - command: the command string to execute
            - sleep: the integer number of seconds
            - comment/noop: None

    Equality is based on op_type and value only (not raw_line), which
    supports the round-trip property: parse → serialize → re-parse
    yields an identical operation list.
    """

    op_type: Literal["noop", "comment", "command", "sleep", "manifest"]
    raw_line: str
    value: str | int | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ManifestOperation):
            return NotImplemented
        if self.op_type != other.op_type:
            return False
        if self.op_type == "comment":
            # Comments are distinguished by their raw text content
            return self.raw_line.strip() == other.raw_line.strip()
        return self.value == other.value

    def __hash__(self) -> int:
        if self.op_type == "comment":
            return hash((self.op_type, self.raw_line.strip()))
        return hash((self.op_type, self.value))


def parse_manifest_list(content: str) -> list[ManifestOperation]:
    """Parse k8s.lst file content into a list of typed operations.

    Processes lines sequentially from top to bottom, classifying each
    line according to its prefix character.

    Classification rules:
        - Blank/whitespace-only → noop
        - First non-whitespace is '#' → comment
        - First non-whitespace is '>' → command (value = remainder stripped)
        - First non-whitespace is '+' followed by valid int > 0 → sleep
        - First non-whitespace is '+' with invalid/non-positive int → sleep(30) + warning
        - Otherwise non-blank → manifest filename (append .yaml if missing)

    Args:
        content: The full text content of a k8s.lst file.

    Returns:
        Ordered list of ManifestOperation instances.
    """
    operations: list[ManifestOperation] = []

    for line in content.split("\n"):
        stripped = line.strip()

        # Blank line → noop
        if not stripped:
            operations.append(ManifestOperation(op_type="noop", raw_line=line))
            continue

        # Comment line: first non-whitespace is '#'
        if stripped.startswith("#"):
            operations.append(ManifestOperation(op_type="comment", raw_line=line))
            continue

        # Command line: first non-whitespace is '>'
        if stripped.startswith(">"):
            remainder = stripped[1:].strip()
            # Requirement 19.8: empty content after prefix → noop with warning
            if not remainder:
                logger.warning(
                    "command_line_empty",
                    raw_line=line,
                    msg="Command line has no content after '>', treating as no-op",
                )
                operations.append(ManifestOperation(op_type="noop", raw_line=line))
            else:
                operations.append(
                    ManifestOperation(op_type="command", raw_line=line, value=remainder)
                )
            continue

        # Sleep line: first non-whitespace is '+'
        if stripped.startswith("+"):
            remainder = stripped[1:].strip()
            # Requirement 19.8: empty content after prefix → noop with warning
            if not remainder:
                logger.warning(
                    "sleep_line_empty",
                    raw_line=line,
                    msg="Sleep line has no content after '+', treating as no-op",
                )
                operations.append(ManifestOperation(op_type="noop", raw_line=line))
                continue

            try:
                seconds = int(remainder)
                if seconds > 0:
                    operations.append(
                        ManifestOperation(op_type="sleep", raw_line=line, value=seconds)
                    )
                else:
                    # Non-positive integer → warning + default 30s
                    logger.warning(
                        "invalid_sleep_value",
                        raw_line=line,
                        parsed_value=seconds,
                        msg="Sleep value must be > 0, defaulting to 30 seconds",
                    )
                    operations.append(
                        ManifestOperation(op_type="sleep", raw_line=line, value=30)
                    )
            except ValueError:
                # Non-integer after '+' → warning + default 30s
                logger.warning(
                    "unparseable_sleep_value",
                    raw_line=line,
                    unparseable_value=remainder,
                    msg="Cannot parse sleep value as integer, defaulting to 30 seconds",
                )
                operations.append(
                    ManifestOperation(op_type="sleep", raw_line=line, value=30)
                )
            continue

        # Manifest filename: non-blank, no special prefix
        filename = stripped
        if not filename.endswith(".yaml"):
            logger.warning(
                "manifest_missing_yaml_extension",
                original_filename=filename,
                msg="Manifest filename missing .yaml extension, appending it",
            )
            filename = filename + ".yaml"

        operations.append(
            ManifestOperation(op_type="manifest", raw_line=line, value=filename)
        )

    return operations


def serialize_operations(operations: list[ManifestOperation]) -> str:
    """Serialize a list of ManifestOperations back to k8s.lst text format.

    Produces text that, when re-parsed with parse_manifest_list, yields
    an identical operation list (round-trip property).

    Serialization rules:
        - noop → empty line
        - comment → raw_line (preserves original text)
        - command → '> ' + value
        - sleep → '+ ' + str(value)
        - manifest → value (already includes .yaml)

    Args:
        operations: List of ManifestOperation to serialize.

    Returns:
        Multi-line string representation of the operations.
    """
    lines: list[str] = []

    for op in operations:
        if op.op_type == "noop":
            lines.append("")
        elif op.op_type == "comment":
            lines.append(op.raw_line)
        elif op.op_type == "command":
            lines.append(f"> {op.value}")
        elif op.op_type == "sleep":
            lines.append(f"+ {op.value}")
        elif op.op_type == "manifest":
            lines.append(str(op.value))

    return "\n".join(lines)
