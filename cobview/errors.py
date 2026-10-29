"""Exceptions shared by the codecs, views and arithmetic rules."""


class CobolDataError(ValueError):
    """Bytes that are not a valid value for their field, or a value that cannot be stored."""


class SizeError(CobolDataError):
    """The value does not fit the field: COBOL's ON SIZE ERROR.

    The field is left unchanged, exactly as COBOL leaves the target of a
    statement whose ON SIZE ERROR phrase fires.
    """
