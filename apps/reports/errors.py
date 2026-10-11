from rest_framework.exceptions import APIException


class TooManyExports(APIException):
    status_code = 429
    default_detail = "You already have exports in progress. Wait for one to finish."
    default_code = "too_many_exports"


class ExportNotReady(APIException):
    status_code = 409
    default_detail = "This export is not ready to download."
    default_code = "export_not_ready"


class ExportExpired(APIException):
    status_code = 410
    default_detail = "This export has expired. Request it again."
    default_code = "export_expired"


class InvalidExport(APIException):
    status_code = 400
    default_detail = "This export request is not valid."
    default_code = "invalid_export"


class PackTooLarge(Exception):
    """Raised by the worker: the selection exceeds the pack limits."""
