"""Public canonical-recording builder.

Keep this module thin: canonical schema construction remains deterministic and
must not depend on frame sampling, visualization, tagging, or VLM packages.
"""

from ms_odd_tagging.input_generator.canonical_builder import main, parse_args

__all__ = ["main", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
