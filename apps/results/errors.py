from rest_framework.exceptions import APIException


class ReviewNotEnabled(APIException):
    status_code = 409
    default_detail = "Review is not enabled for this election."
    default_code = "review_not_enabled"


class ResultsFrozen(APIException):
    status_code = 409
    default_detail = "Results can no longer be changed for this election."
    default_code = "results_frozen"


class NotHeadVersion(APIException):
    status_code = 409
    default_detail = "Only the version that currently counts can be reviewed."
    default_code = "not_head_version"


class AlreadyDecided(APIException):
    status_code = 409
    default_detail = "This version is not in a state that allows that decision."
    default_code = "already_decided"


class FlagsUnacknowledged(APIException):
    status_code = 409
    default_detail = "This result has open flags. Acknowledge them to approve it."
    default_code = "flags_unacknowledged"
