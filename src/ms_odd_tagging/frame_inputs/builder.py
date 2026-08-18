"""Public frame-input builder.

The builder consumes canonical recording JSON. It never reads raw OD/LD files
directly; raw annotation normalization belongs to :mod:`ms_odd_tagging.canonical`.
"""

from ms_odd_tagging.input_generator.frame_input_builder import (
    DEFAULT_SIZE,
    main,
    parse_args,
)

__all__ = ["DEFAULT_SIZE", "main", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
