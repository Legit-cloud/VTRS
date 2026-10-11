from rest_framework.exceptions import APIException


class FlagAlreadyClosed(APIException):
    status_code = 409
    default_detail = "This flag is already closed. Reopen it to change it."
    default_code = "flag_already_closed"


class FlagNotClosed(APIException):
    status_code = 409
    default_detail = "Only a closed flag can be reopened."
    default_code = "flag_not_closed"


class InvalidAssignee(APIException):
    status_code = 400
    default_detail = "That person cannot be assigned: they are not active, or cannot see this flag."
    default_code = "invalid_assignee"
